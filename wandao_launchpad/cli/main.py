"""CLI 子命令层——与 GUI 共用同一套 ProcessManager/ConfigStore。

契约：
- 每个子命令支持 --json，输出**单行 JSON**（stdout 仅此一行，人类可读文案走 stderr）。
- 退出码见 exitcodes.py，稳定不变。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .. import __version__
from ..config import ConfigStore
from ..constants import pidfile_path
from ..context import build_context
from ..process_manager import ProcessManager
from . import exitcodes as ec


def _emit(payload: dict, as_json: bool, human: str | None = None) -> None:
    if as_json:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    elif human is not None:
        sys.stdout.write(human + "\n")
    sys.stdout.flush()


def _load_ctx(store: ConfigStore, env_id: str | None):
    cfg = store.load()
    if not cfg.environments:
        return None, "尚未配置任何环境：请先运行 GUI 完成设置（或在 config.json 里配置 environments）"
    try:
        return build_context(cfg, env_id), None
    except LookupError as exc:
        return None, str(exc)


# ---------- 子命令实现 ----------

def cmd_start(args) -> int:
    store = ConfigStore(Path(args.home) if args.home else None)
    ctx, err = _load_ctx(store, args.env)
    if ctx is None:
        _emit({"ok": False, "error": err}, args.json, f"错误: {err}")
        return ec.EXIT_ERROR
    pm = ProcessManager(ctx, pidfile_path(store.config_dir))
    res = pm.start(wait_timeout=args.timeout, no_wait=args.no_wait)
    payload = {
        "started": res.started, "pid": res.pid, "port": res.port, "url": res.url,
        "ready": res.ready, "elapsed_sec": round(res.elapsed_sec, 2),
        "log_path": res.log_path, "error": res.error,
        "running_env_id": res.running_env_id or None,
    }
    if res.started and (res.ready or args.no_wait):
        _emit(payload, args.json, f"已启动: {res.url} (PID={res.pid})")
        return ec.EXIT_OK
    if not res.started and res.running_env_id:
        _emit(payload, args.json, f"已在跑 (env={res.running_env_id})，拒绝重复启动")
        return ec.EXIT_ALREADY_RUNNING
    _emit(payload, args.json, f"启动失败: {res.error}")
    return ec.EXIT_ERROR


def cmd_stop(args) -> int:
    store = ConfigStore(Path(args.home) if args.home else None)
    ctx, err = _load_ctx(store, None)  # stop 作用于"当前在跑的那个"，不认 --env
    if ctx is None:
        _emit({"ok": False, "error": err}, args.json, f"错误: {err}")
        return ec.EXIT_ERROR
    pm = ProcessManager(ctx, pidfile_path(store.config_dir))
    res = pm.stop()
    payload = {"stopped": res.stopped, "pid": res.pid,
               "elapsed_sec": round(res.elapsed_sec, 2), "error": res.error}
    _emit(payload, args.json,
          "无实例在跑" if not res.stopped and res.pid is None
          else (f"已停止 PID={res.pid}" if res.stopped else f"停止失败: {res.error}"))
    return ec.EXIT_OK if (res.stopped or res.pid is None) else ec.EXIT_ERROR


def cmd_status(args) -> int:
    store = ConfigStore(Path(args.home) if args.home else None)
    ctx, err = _load_ctx(store, None)
    if ctx is None:
        _emit({"ok": False, "error": err}, args.json, f"错误: {err}")
        return ec.EXIT_ERROR
    pm = ProcessManager(ctx, pidfile_path(store.config_dir))
    st = pm.status()
    payload = dict(st, ok=True)
    _emit(payload, args.json,
          f"运行中: {st['url']} (PID={st['pid']})" if st["running"] else "未运行")
    return ec.EXIT_OK if st["running"] else ec.EXIT_NOT_RUNNING


def cmd_restart(args) -> int:
    store = ConfigStore(Path(args.home) if args.home else None)
    ctx, err = _load_ctx(store, args.env)
    if ctx is None:
        _emit({"ok": False, "error": err}, args.json, f"错误: {err}")
        return ec.EXIT_ERROR
    pm = ProcessManager(ctx, pidfile_path(store.config_dir))
    stop_res = pm.stop()
    start_res = pm.start(wait_timeout=args.timeout, no_wait=args.no_wait)
    payload = {
        "stopped": stop_res.stopped, "started": start_res.started,
        "ready": start_res.ready, "pid": start_res.pid, "port": start_res.port,
        "url": start_res.url, "elapsed_sec": round(start_res.elapsed_sec, 2),
        "error": start_res.error or stop_res.error,
    }
    ok = start_res.started and (start_res.ready or args.no_wait)
    _emit(payload, args.json, f"重启就绪: {start_res.url}" if ok else f"重启失败: {payload['error']}")
    return ec.EXIT_OK if ok else ec.EXIT_ERROR


def cmd_info(args) -> int:
    store = ConfigStore(Path(args.home) if args.home else None)
    cfg = store.load()
    active = cfg.active_env()
    payload = {
        "launcher_version": __version__,
        "schema_version": cfg.schema_version,
        "active_env_id": cfg.active_env_id,
        "environments": [e.to_dict() for e in cfg.environments],
        "comfyui_root": active.comfyui_root if active else None,
        "python_path": active.python_path if active else None,
        "port": cfg.launch.port,
        "launch": cfg.launch.to_dict(),
        "mirrors": cfg.mirrors.to_dict(),
        "config_path": str(store.path),
    }
    _emit(payload, args.json, json.dumps(payload, ensure_ascii=False, indent=2))
    return ec.EXIT_OK


def cmd_logs(args) -> int:
    store = ConfigStore(Path(args.home) if args.home else None)
    ctx, err = _load_ctx(store, None)
    if ctx is None:
        _emit({"ok": False, "error": err}, args.json, f"错误: {err}")
        return ec.EXIT_ERROR
    target = args.target
    path = {
        "comfyui": ctx.comfyui_log,
        "launcher": store.config_dir / "logs" / "launchpad.log",
    }.get(target)
    if path is None or not path.exists():
        _emit({"ok": False, "error": f"日志不存在: {target} ({path})"},
              args.json, f"日志不存在: {target}")
        return ec.EXIT_ERROR
    lines = _tail_lines(path, args.lines)
    sys.stdout.write(lines + "\n")
    if args.follow:
        _follow(path)
    return ec.EXIT_OK


def _tail_lines(path: Path, n: int) -> str:
    """真 tail：从文件尾部按块回退，不整读大文件（Mie 的假二分教训）。"""
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        end = fh.tell()
        remaining = n
        chunks: list[bytes] = []
        pos = end
        block = 8192
        while pos > 0 and remaining > 0:
            step = min(block, pos)
            pos -= step
            fh.seek(pos)
            data = fh.read(step)
            cnt = data.count(b"\n")
            chunks.append(data)
            if cnt >= remaining:
                break
        buf = b"".join(reversed(chunks))
    lines = buf.decode("utf-8", errors="replace").splitlines()[-n:]
    return "\n".join(lines)


def _follow(path: Path) -> None:
    """tail -f。注意：会阻塞，自动化脚本禁用（--no-follow）。"""
    import select  # noqa: F401  (Windows 无 select-on-file，用轮询)
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        while True:
            line = fh.readline()
            if line:
                sys.stdout.write(line.decode("utf-8", errors="replace"))
                sys.stdout.flush()
            else:
                time.sleep(0.5)


# ---------- 参数解析 ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="wandao-launchpad",
        description="万道启动台 —— ComfyUI 启动器（无参数启动 GUI；带子命令为 headless CLI）")
    p.add_argument("--json", action="store_true", help="以单行 JSON 输出，便于脚本解析")
    p.add_argument("--home", default=None, help="配置目录（默认：包所在目录/launchpad）")
    sub = p.add_subparsers(dest="command")

    sp = sub.add_parser("start", help="启动 ComfyUI（阻塞到就绪或超时）")
    sp.add_argument("--no-wait", action="store_true", help="spawn 后立即返回")
    sp.add_argument("--timeout", type=float, default=60.0, help="等待就绪上限秒数")
    sp.add_argument("--env", default=None, help="一次性指定环境 id（默认用激活环境）")
    sp.set_defaults(func=cmd_start)

    sp = sub.add_parser("stop", help="停止 ComfyUI（幂等；作用于当前在跑的实例）")
    sp.set_defaults(func=cmd_stop)

    sp = sub.add_parser("status", help="查询运行状态")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("restart", help="先停后启")
    sp.add_argument("--no-wait", action="store_true")
    sp.add_argument("--timeout", type=float, default=60.0)
    sp.add_argument("--env", default=None)
    sp.set_defaults(func=cmd_restart)

    sp = sub.add_parser("info", help="打印当前生效配置（不启动任何东西）")
    sp.add_argument("--env", default=None)
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("logs", help="查看日志（comfyui/launcher）")
    sp.add_argument("target", choices=["comfyui", "launcher"], default="comfyui",
                    nargs="?", help="日志目标")
    sp.add_argument("-n", "--lines", type=int, default=100)
    sp.add_argument("-f", "--follow", dest="follow", action="store_true",
                    help="持续跟踪（阻塞！自动化脚本用默认 no-follow）")
    sp.add_argument("--no-follow", dest="follow", action="store_false")
    sp.set_defaults(func=cmd_logs, follow=False)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return ec.EXIT_ERROR
    return args.func(args)

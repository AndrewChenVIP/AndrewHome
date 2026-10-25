"""CLI 子命令层——与 GUI 共用同一套 ProcessManager/ConfigStore。

契约：
- 每个子命令支持 --json，输出**单行 JSON**（stdout 仅此一行，人类可读文案走 stderr）。
- 退出码见 exitcodes.py，稳定不变。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from .. import __version__
from ..config import ConfigStore
from ..constants import pidfile_path
from ..context import build_context
from ..process_manager import ProcessManager
from . import exitcodes as ec

logger = logging.getLogger(__name__)


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
        "external": res.external,
    }
    if res.started and (res.ready or args.no_wait):
        _emit(payload, args.json, f"已启动: {res.url} (PID={res.pid})")
        return ec.EXIT_OK
    if not res.started and (res.running_env_id or res.external):
        who = f"env={res.running_env_id}" if res.running_env_id else "外部实例"
        _emit(payload, args.json, f"已在跑（{who}），拒绝重复启动")
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
    resolved_root = active.comfyui_root if active else None
    resolved_py = active.python_path if active else None
    env_note = "active"
    if getattr(args, "env", None):
        try:
            from ..context import build_context
            ctx = build_context(cfg, args.env)
            resolved_root, resolved_py = ctx.env.comfyui_root, ctx.env.python_path
            env_note = f"--env={args.env}"
        except LookupError as exc:
            _emit({"ok": False, "error": str(exc)}, args.json, f"错误: {exc}")
            return ec.EXIT_ERROR
    payload = {
        "launcher_version": __version__,
        "schema_version": cfg.schema_version,
        "active_env_id": cfg.active_env_id,
        "environments": [e.to_dict() for e in cfg.environments],
        "comfyui_root": resolved_root,
        "python_path": resolved_py,
        "resolved_from": env_note,
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


# ---------- 插件 / 内核 / 模型库 ----------

def _custom_nodes_dir(ctx) -> Path:
    return ctx.comfyui_root / "ComfyUI" / "custom_nodes"


def _pip_index(store: ConfigStore) -> str | None:
    from ..network import pip_index_url
    return pip_index_url(store.load().mirrors.pypi)


def _ensure_plugin_deps(ctx, store: ConfigStore, plugin_path: Path) -> dict | None:
    """装插件 requirements（有才跑）。失败只随 payload 上报，不中断主流程。"""
    from .. import pipx
    try:
        return pipx.ensure_requirements(plugin_path, ctx.python_exe,
                                        index_url=_pip_index(store))
    except Exception as exc:  # noqa: BLE001 —— 依赖失败不拖垮安装结果
        logger.warning("插件依赖安装异常: %s", plugin_path, exc_info=True)
        return {"ran": True, "ok": False, "log": "", "reason": str(exc)}


def cmd_plugins(args) -> int:
    from ..plugins import PluginService

    store = ConfigStore(Path(args.home) if args.home else None)
    ctx, err = _load_ctx(store, None)
    if ctx is None:
        _emit({"ok": False, "error": err}, args.json, f"错误: {err}")
        return ec.EXIT_ERROR
    svc = PluginService(_custom_nodes_dir(ctx), cache_dir=store.config_dir,
                        github_proxy=ctx.config.mirrors.github_proxy)

    try:
        if args.action == "list":
            items = svc.list()
            payload = {"ok": True, "count": len(items),
                       "plugins": [p.__dict__ for p in items]}
            _emit(payload, args.json, f"{len(items)} 个插件（git {sum(1 for p in items if p.is_git)}"
                                       f"，停用 {sum(1 for p in items if not p.enabled)}）")
            return ec.EXIT_OK
        if args.action == "search":
            query = args.query or args.extra or args.name or ""
            entries = svc.search(query)
            payload = {"ok": True, "count": len(entries),
                       "results": [e.__dict__ for e in entries]}
            _emit(payload, args.json,
                  "\n".join(f"{e.name}  [{e.author}]  {e.install_url}"
                            for e in entries[:20]) or "（无结果）")
            return ec.EXIT_OK
        if args.action == "install":
            target = args.target or args.extra or args.name or ""
            if not target:
                _emit({"ok": False, "error": "缺少目标（git URL 或插件名）"},
                      args.json, "缺少目标")
                return ec.EXIT_ERROR
            info = svc.install(target)
            deps = None
            if not args.no_deps:
                deps = _ensure_plugin_deps(ctx, store, _custom_nodes_dir(ctx) / info.dir_name)
            payload = {"ok": True, "action": "install", "plugin": info.__dict__,
                       "deps": deps}
            msg = f"已安装 {info.dir_name}"
            if deps and deps.get("ran") and not deps.get("ok"):
                msg += "（依赖安装失败，见 deps.log）"
            elif deps and deps.get("ran"):
                msg += "（依赖已装）"
            _emit(payload, args.json, msg)
            return ec.EXIT_OK
        if args.action in ("enable", "disable"):
            if not args.name:
                _emit({"ok": False, "error": "缺少插件名"}, args.json, "缺少插件名")
                return ec.EXIT_ERROR
            info = svc.set_enabled(args.name, args.action == "enable")
            payload = {"ok": True, "action": args.action, "plugin": info.__dict__}
            _emit(payload, args.json, f"已{args.action} {info.dir_name}")
            return ec.EXIT_OK
        if args.action == "uninstall":
            if not args.name:
                _emit({"ok": False, "error": "缺少插件名"}, args.json, "缺少插件名")
                return ec.EXIT_ERROR
            if not args.yes:
                _emit({"ok": False, "error": "卸载需 --yes 确认（不可恢复）"},
                      args.json, "卸载需 --yes 确认")
                return ec.EXIT_ERROR
            svc.uninstall(args.name)
            _emit({"ok": True, "action": "uninstall", "target": args.name},
                  args.json, f"已卸载 {args.name}")
            return ec.EXIT_OK
        if args.action == "check-updates":
            results = svc.check_updates()
            outdated = [r["dir_name"] for r in results if r["outdated"]]
            payload = {"ok": True, "checked": len(results),
                       "outdated": outdated, "results": results}
            _emit(payload, args.json,
                  f"检查 {len(results)} 个，可更新 {len(outdated)} 个"
                  + (f": {', '.join(outdated[:10])}" if outdated else ""))
            return ec.EXIT_OK
        if args.action == "update-all":
            results = svc.update_all()
            if not args.no_deps:
                for r in results:
                    if r.get("ok") and r.get("changed"):
                        r["deps"] = _ensure_plugin_deps(
                            ctx, store, _custom_nodes_dir(ctx) / r["dir_name"])
            all_ok = all(r["ok"] for r in results)
            payload = {"ok": all_ok, "count": len(results), "results": results}
            _emit(payload, args.json,
                  f"更新完成 {sum(1 for r in results if r['ok'])}/{len(results)}"
                  f"（跳过 {sum(1 for r in results if r['skipped'])}）")
            return ec.EXIT_OK if all_ok else ec.EXIT_ERROR
        if args.action == "update":
            if not args.name:
                _emit({"ok": False, "error": "缺少插件名"}, args.json, "缺少插件名")
                return ec.EXIT_ERROR
            result = svc.update_one(args.name)
            if result.get("ok") and result.get("changed") and not args.no_deps:
                result["deps"] = _ensure_plugin_deps(
                    ctx, store, _custom_nodes_dir(ctx) / args.name)
            payload = {"ok": result["ok"], **result}
            _emit(payload, args.json,
                  f"已更新 {args.name}" if result["ok"] else f"未更新 {args.name}: {result['detail']}")
            return ec.EXIT_OK if result["ok"] else ec.EXIT_ERROR
    except (FileNotFoundError, RuntimeError) as exc:
        _emit({"ok": False, "error": str(exc)}, args.json, f"错误: {exc}")
        return ec.EXIT_ERROR

    _emit({"ok": False, "error": f"未知操作: {args.action}"}, args.json,
          f"未知操作: {args.action}")
    return ec.EXIT_ERROR


def cmd_kernel(args) -> int:
    from ..kernel import KernelService

    store = ConfigStore(Path(args.home) if args.home else None)
    ctx, err = _load_ctx(store, None)
    if ctx is None:
        _emit({"ok": False, "error": err}, args.json, f"错误: {err}")
        return ec.EXIT_ERROR
    svc = KernelService(ctx.comfyui_root / "ComfyUI",
                        base_url=None if args.action == "info" else ctx.base_url)

    try:
        if args.action == "info":
            info = svc.info()
            payload = {"ok": True, **info.__dict__}
            _emit(payload, args.json,
                  f"ComfyUI {info.comfyui_version} @ {info.commit}"
                  f"{'（有未提交改动）' if info.dirty else ''}")
            return ec.EXIT_OK
        if args.action == "update":
            result = svc.update(dry_run=args.dry_run, stable_only=args.stable_only)
            deps = None
            if result["updated"] and args.sync_deps and not args.dry_run:
                from .. import pipx
                deps = pipx.sync_comfy_requirements(
                    ctx.comfyui_root / "ComfyUI", ctx.python_exe,
                    index_url=_pip_index(store))
            payload = {"ok": True, **result, "deps": deps}
            code = ec.EXIT_OK if result["updated"] else ec.EXIT_ALREADY_LATEST
            msg = (f"已更新 → {result['to']}" if result["updated"]
                   else f"已是最新（{result['to']}）")
            if deps:
                if deps.get("ran") and deps.get("ok"):
                    msg += f"（依赖已同步，冻结剔除 {len(deps.get('dropped', []))} 项）"
                elif deps.get("ran"):
                    msg += "（依赖同步失败：pip 非零退出，CUDA 栈未受影响）"
            _emit(payload, args.json, msg)
            return code
        if args.action == "log":
            rows = svc.log(count=args.lines, skip=args.skip)
            payload = {"ok": True, "count": len(rows), "commits": rows}
            _emit(payload, args.json,
                  "\n".join(f"{r['commit']} {r['date'][:10]} {r['subject'][:60]}"
                            for r in rows) or "（无提交）")
            return ec.EXIT_OK
        if args.action == "checkout":
            if not args.yes:
                _emit({"ok": False, "error": "切换内核版本需 --yes 确认"}, args.json,
                      "切换内核版本需 --yes 确认")
                return ec.EXIT_ERROR
            commit = svc.checkout(args.ref)
            _emit({"ok": True, "checked_out": commit}, args.json, f"已切换到 {commit}")
            return ec.EXIT_OK
    except RuntimeError as exc:
        _emit({"ok": False, "error": str(exc)}, args.json, f"错误: {exc}")
        return ec.EXIT_ERROR
    return ec.EXIT_ERROR


def cmd_models(args) -> int:
    from ..model_paths import ModelPathsService

    store = ConfigStore(Path(args.home) if args.home else None)
    ctx, err = _load_ctx(store, None)
    if ctx is None:
        _emit({"ok": False, "error": err}, args.json, f"错误: {err}")
        return ec.EXIT_ERROR
    svc = ModelPathsService(ctx.comfyui_root / "ComfyUI", store.config_dir)

    if args.action == "list":
        libs = svc.load_libraries()
        payload = {"ok": True, "count": len(libs),
                   "libraries": [{**l.__dict__,
                                  "effective_mappings": svc.effective_mappings(l)}
                                 for l in libs]}
        _emit(payload, args.json,
              f"{len(libs)} 个库（启用 {sum(1 for l in libs if l.enabled)}）")
        return ec.EXIT_OK
    if args.action == "import":
        n = svc.import_existing()
        _emit({"ok": True, "imported": n}, args.json,
              f"导入 {n} 个库" if n else "无可导入（sidecar 已存在或无 yaml）")
        return ec.EXIT_OK
    if args.action == "validate":
        problems = svc.validate()
        payload = {"ok": not problems, "problems": problems}
        _emit(payload, args.json,
              "体检通过" if not problems else f"{len(problems)} 个问题:\n" + "\n".join(problems))
        return ec.EXIT_OK if not problems else ec.EXIT_ERROR
    if args.action == "apply":
        result = svc.apply()
        _emit({"ok": True, **result}, args.json,
              f"已写入 {result['libraries']} 库 / {result['mappings']} 映射"
              + (f"（备份: {result['backup']}）" if result["backup"] else ""))
        return ec.EXIT_OK
    return ec.EXIT_ERROR


def cmd_support(args) -> int:
    from ..support import build_support_zip

    store = ConfigStore(Path(args.home) if args.home else None)
    ctx, err = _load_ctx(store, None)
    if ctx is None:
        _emit({"ok": False, "error": err}, args.json, f"错误: {err}")
        return ec.EXIT_ERROR
    out = Path(args.out) if args.out else None
    path = build_support_zip(ctx, pidfile_path(store.config_dir), out)
    _emit({"ok": True, "zip_path": str(path)}, args.json, f"支持包已生成: {path}")
    return ec.EXIT_OK


def cmd_doctor(args) -> int:
    from ..doctor import blockers, run_checks, summarize

    store = ConfigStore(Path(args.home) if args.home else None)
    ctx, err = _load_ctx(store, None)
    if ctx is None:
        _emit({"ok": False, "error": err}, args.json, f"错误: {err}")
        return ec.EXIT_ERROR
    checks = run_checks(ctx, quick=args.quick, config_dir=store.config_dir)
    nf, nw = summarize(checks)
    icon = {"ok": "✓", "warn": "⚠", "fail": "✗"}
    lines = [f"{icon.get(c['level'], '·')} {c['name']}: {c['detail']}" for c in checks]
    payload = {"ok": nf == 0, "fail": nf, "warn": nw, "checks": checks}
    _emit(payload, args.json,
          "\n".join(lines) + f"\n结论: {'✗ 有 ' + str(nf) + ' 项阻塞，先解决再启动' if nf else '✓ 无阻塞' + (f'（{nw} 项提醒）' if nw else '')}")
    return ec.EXIT_OK if nf == 0 else ec.EXIT_ERROR


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
    sp.add_argument("--timeout", type=float, default=180.0, help="等待就绪上限秒数")
    sp.add_argument("--env", default=None, help="一次性指定环境 id（默认用激活环境）")
    sp.set_defaults(func=cmd_start)

    sp = sub.add_parser("stop", help="停止 ComfyUI（幂等；作用于当前在跑的实例）")
    sp.set_defaults(func=cmd_stop)

    sp = sub.add_parser("status", help="查询运行状态")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("restart", help="先停后启")
    sp.add_argument("--no-wait", action="store_true")
    sp.add_argument("--timeout", type=float, default=180.0)
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

    sp = sub.add_parser("plugins", help="管理 custom_nodes 插件")
    sp.add_argument("action", choices=["list", "enable", "disable", "uninstall",
                                       "check-updates", "update", "update-all",
                                       "search", "install"])
    sp.add_argument("name", nargs="?", help="目标插件 dir_name（list/check/update-all 不需要）")
    sp.add_argument("extra", nargs="?", help="search 的关键词 / install 的 URL")
    sp.add_argument("--query", default=None, help="search 关键词（也可用位置参数）")
    sp.add_argument("--target", default=None, help="install 目标（也可用位置参数）")
    sp.add_argument("--yes", action="store_true", help="危险操作确认位（uninstall）")
    sp.add_argument("--no-deps", dest="no_deps", action="store_true",
                    help="跳过 requirements.txt 依赖安装（install/update/update-all）")
    sp.set_defaults(func=cmd_plugins)

    sp = sub.add_parser("kernel", help="ComfyUI 内核版本管理")
    sp.add_argument("action", choices=["info", "update", "log", "checkout"])
    sp.add_argument("ref", nargs="?", help="checkout 目标（commit/tag/branch）")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--stable-only", action="store_true", help="只更新到稳定版标签")
    sp.add_argument("--sync-deps", dest="sync_deps", action="store_true",
                    help="更新成功后同步 requirements（only-if-needed 升级，"
                         "torch/torchvision/torchaudio/triton 永不动）")
    sp.add_argument("-n", "--lines", type=int, default=50, help="log 条数")
    sp.add_argument("--skip", type=int, default=0, help="log 分页偏移")
    sp.add_argument("--yes", action="store_true", help="checkout 确认位")
    sp.set_defaults(func=cmd_kernel)

    sp = sub.add_parser("doctor", help="启动前体检（环境/入口/端口/磁盘/依赖/内核/模型库）")
    sp.add_argument("--quick", action="store_true",
                    help="只跑无子进程的快检查（启动预检同款）")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("models", help="外置模型库（extra_model_paths.yaml）")
    sp.add_argument("action", choices=["list", "import", "validate", "apply"])
    sp.set_defaults(func=cmd_models)

    sp = sub.add_parser("support", help="打包排障支持包（info+日志）为 zip")
    sp.add_argument("--out", default=None, help="输出 zip 路径（默认配置目录/support-时间戳.zip）")
    sp.set_defaults(func=cmd_support)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return ec.EXIT_ERROR
    # JSON 契约不依赖控制台代码页：英文 Windows 默认 cp1252 编不出中文
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        logger.debug("stdout 重配置跳过（非 TextIOWrapper 或不可重配）", exc_info=True)
    return args.func(args)

"""启动前体检——把"点了没反应"提前变成"哪里不行一屏说清"。

检查分级：fail（阻塞启动）/ warn（能用但要注意）/ ok。
quick 模式（启动前预检用）只跑无子进程的快检查。
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

from .context import AppContext
from .probe import probe

logger = logging.getLogger(__name__)

DISK_WARN_GB = 5.0
DISK_FAIL_GB = 1.0


def _add(checks: list[dict], name: str, level: str, detail: str) -> None:
    checks.append({"name": name, "level": level, "detail": detail})


def run_checks(ctx: AppContext, quick: bool = False,
               config_dir: Path | None = None) -> list[dict]:
    checks: list[dict] = []

    # 1) Python 可执行文件
    py = ctx.env.python_path
    if not py:
        _add(checks, "Python", "warn", "未配置，将用系统 python")
    elif Path(py).exists():
        _add(checks, "Python", "ok", py)
    else:
        _add(checks, "Python", "fail", f"找不到: {py}")

    # 2) main.py
    main = ctx.main_script
    if main.exists():
        _add(checks, "ComfyUI 入口", "ok", str(main))
    else:
        _add(checks, "ComfyUI 入口", "fail", f"找不到 main.py（根目录配错？）: {main}")

    # 3) 端口（无子进程；probe 最多 3s）
    if probe(ctx.base_url):
        _add(checks, "端口", "warn", f"{ctx.base_url} 已有服务在答话（重复启动会被拒绝）")
    else:
        _add(checks, "端口", "ok", f"{ctx.base_url} 空闲")

    # 4) 磁盘剩余（ComfyUI 根所在盘；输出/模型都落这里）
    try:
        usage = shutil.disk_usage(str(ctx.comfyui_root))
        free_gb = usage.free / 1024**3
        if free_gb < DISK_FAIL_GB:
            _add(checks, "磁盘", "fail", f"剩余 {free_gb:.1f}GB（不足 {DISK_FAIL_GB:.0f}GB，输出/模型写入可能失败）")
        elif free_gb < DISK_WARN_GB:
            _add(checks, "磁盘", "warn", f"剩余 {free_gb:.1f}GB（偏少）")
        else:
            _add(checks, "磁盘", "ok", f"剩余 {free_gb:.1f}GB")
    except OSError as exc:
        logger.debug("磁盘检查失败", exc_info=True)
        _add(checks, "磁盘", "warn", f"无法检查: {exc}")

    if quick:
        return checks

    # 5) pip 可用（子进程 ~1-2s；依赖联动的前提）
    rc, out, _err = _run_quiet([ctx.python_exe, "-m", "pip", "--version"])
    if rc == 0:
        _add(checks, "pip", "ok", (out or "").splitlines()[0][:80] if out else "可用")
    else:
        _add(checks, "pip", "warn", "pip 不可用——插件依赖联动与内核依赖同步将无法工作")

    # 6) 内核 git 状态
    git_dir = ctx.comfyui_root / "ComfyUI" / ".git"
    if not git_dir.exists():
        _add(checks, "内核仓库", "warn", "ComfyUI 不是 git 仓库——内核版本管理不可用")
    else:
        from .kernel import KernelService
        try:
            info = KernelService(ctx.comfyui_root / "ComfyUI").info()
            if info.dirty:
                _add(checks, "内核仓库", "warn", f"工作树脏（{info.commit}）——内核更新会被拒绝")
            else:
                _add(checks, "内核仓库", "ok", f"{info.comfyui_version} @ {info.commit}")
        except Exception as exc:  # noqa: BLE001 —— 体检单项失败不拖垮整体
            logger.debug("内核信息读取失败", exc_info=True)
            _add(checks, "内核仓库", "warn", f"读取失败: {exc}")

    # 7) extra_model_paths.yaml（若存在，解析体检）
    yaml_path = ctx.comfyui_root / "ComfyUI" / "extra_model_paths.yaml"
    if yaml_path.exists():
        try:
            import yaml
            data = yaml.safe_load(yaml_path.read_text(encoding="utf-8-sig")) or {}
            _add(checks, "模型路径 yaml", "ok", f"可解析（{len(data)} 个库）" if isinstance(data, dict)
                 else "格式异常（顶层不是映射）")
            if not isinstance(data, dict):
                checks[-1]["level"] = "warn"
        except Exception as exc:  # noqa: BLE001
            logger.debug("yaml 解析失败", exc_info=True)
            _add(checks, "模型路径 yaml", "warn", f"解析失败: {str(exc)[:120]}")

    # 8) 模型库 sidecar 体检（需要 config_dir；没有就跳过）
    if config_dir is not None:
        try:
            from .model_paths import ModelPathsService
            svc = ModelPathsService(ctx.comfyui_root / "ComfyUI", config_dir)
            problems = svc.validate()
            if problems:
                _add(checks, "模型库", "warn",
                     f"{len(problems)} 个问题: {problems[0][:80]}…")
            else:
                n = len(svc.load_libraries())
                _add(checks, "模型库", "ok", f"{n} 个库体检通过" if n else "未配置（可选）")
        except Exception as exc:  # noqa: BLE001 —— 体检单项失败不拖垮整体
            logger.debug("模型库体检失败", exc_info=True)
            _add(checks, "模型库", "warn", f"体检失败: {exc}")

    return checks


def _run_quiet(cmd: list[str]) -> tuple[int, str, str]:
    from .proc import run_hidden
    try:
        return run_hidden(cmd, timeout=30.0)
    except Exception as exc:  # noqa: BLE001
        logger.debug("体检子进程失败: %s", cmd, exc_info=True)
        return -1, "", str(exc)


def summarize(checks: list[dict]) -> tuple[int, int]:
    """返回 (fail 数, warn 数)。"""
    fails = sum(1 for c in checks if c["level"] == "fail")
    warns = sum(1 for c in checks if c["level"] == "warn")
    return fails, warns


def blockers(checks: list[dict]) -> list[dict]:
    return [c for c in checks if c["level"] == "fail"]

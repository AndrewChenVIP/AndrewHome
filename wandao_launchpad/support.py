"""支持包——一键打包排障材料（对应 Mie 的"打包日志"按钮）。

zip 内容：info.json（版本/环境/启动选项/内核/插件清单/状态）＋ 启动器日志全文
＋ comfyui 日志尾部（大日志不整读）。
"""
from __future__ import annotations

import json
import logging
import zipfile
from datetime import datetime
from pathlib import Path

from . import __version__
from .context import AppContext
from .constants import launcher_log_path
from .process_manager import ProcessManager

logger = logging.getLogger(__name__)

COMFYUI_LOG_TAIL_LINES = 500


def _tail_text(path: Path, lines: int) -> str:
    """复用 CLI 的真 tail（按块回退），返回文本。"""
    from .cli.main import _tail_lines
    try:
        return _tail_lines(path, lines)
    except OSError:
        logger.debug("日志读取失败: %s", path, exc_info=True)
        return ""


def build_support_zip(ctx: AppContext, pidfile_p: Path, out: Path | None = None) -> Path:
    out = out or (pidfile_p.parent / f"support-{datetime.now():%Y%m%d-%H%M%S}.zip")
    out.parent.mkdir(parents=True, exist_ok=True)

    status = ProcessManager(ctx, pidfile_p).status()
    payload: dict = {
        "launcher_version": __version__,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "environment": ctx.env.to_dict(),
        "launch_options": ctx.launch.to_dict(),
        "mirrors": ctx.config.mirrors.to_dict(),
        "status": status,
    }

    # 内核与插件信息（失败不阻塞打包——排障包要的是"现场"，不是完美）
    try:
        from .kernel import KernelService
        payload["kernel"] = KernelService(ctx.comfyui_root / "ComfyUI").info().__dict__
    except Exception as exc:  # noqa: BLE001 —— 附带信息，尽力而为
        logger.debug("内核信息收集失败", exc_info=True)
        payload["kernel"] = {"error": str(exc)}
    try:
        from .plugins import PluginService
        payload["plugins"] = [p.__dict__ for p in
                              PluginService(ctx.comfyui_root / "ComfyUI" / "custom_nodes").list()]
    except Exception as exc:  # noqa: BLE001
        logger.debug("插件清单收集失败", exc_info=True)
        payload["plugins"] = {"error": str(exc)}

    launcher_log = launcher_log_path(pidfile_p.parent)
    comfy_log = ctx.comfyui_log

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("info.json", json.dumps(payload, ensure_ascii=False, indent=2))
        if launcher_log.exists():
            zf.write(launcher_log, "launchpad.log")
        if comfy_log.exists():
            zf.writestr("comfyui-tail.log", _tail_text(comfy_log, COMFYUI_LOG_TAIL_LINES))
    return out

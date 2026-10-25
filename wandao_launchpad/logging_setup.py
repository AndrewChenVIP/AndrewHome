"""启动台自身日志：轮转文件 + 控制台，一次装配。"""

from __future__ import annotations

import logging
import logging.handlers
import sys

from .constants import launcher_log_path

_CONFIGURED = False


def setup_logging(level: int = logging.INFO, config_dir=None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    path = launcher_log_path(config_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("wandao_launchpad")
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    fh = logging.handlers.RotatingFileHandler(
        path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    ch = logging.StreamHandler(sys.stderr)
    ch.setFormatter(fmt)
    root.addHandler(ch)
    _CONFIGURED = True

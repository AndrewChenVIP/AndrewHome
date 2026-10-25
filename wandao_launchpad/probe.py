"""/system_stats 就绪探测——用 ComfyUI 自己的 API 判断，不猜。"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from .constants import PROBE_TIMEOUT_SEC

logger = logging.getLogger(__name__)


def probe(base_url: str, timeout: float = PROBE_TIMEOUT_SEC) -> bool:
    """GET <base_url>/system_stats，2xx 即就绪。"""
    url = base_url.rstrip("/") + "/system_stats"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "WandaoLaunchpad/0.1"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def wait_ready(base_url: str, deadline_sec: float, poll_interval: float = 1.0,
               elapsed_cb=None) -> bool:
    """轮询直到就绪或超时。elapsed_cb(elapsed) 供 GUI 刷进度，可None。"""
    import time

    start = time.monotonic()
    while True:
        if probe(base_url, timeout=min(PROBE_TIMEOUT_SEC, max(0.5, poll_interval))):
            return True
        elapsed = time.monotonic() - start
        if elapsed_cb:
            try:
                elapsed_cb(elapsed)
            except Exception:
                logger.debug("elapsed_cb 回调失败", exc_info=True)
        if elapsed >= deadline_sec:
            return False
        time.sleep(poll_interval)

"""开机自启（Windows 任务计划）——冻结版专用的一键注册/取消。

任务动作 = 直接拉起便携 exe（无参数 = GUI）。开发模式（非冻结）不可用，
因为 /TR 单值装不下"python -m 包名 gui"的可靠引号组合，宁可不做。
"""
from __future__ import annotations

import logging
import sys

from .proc import run_hidden

logger = logging.getLogger(__name__)

TASK_NAME = "WandaoLaunchpadGUI"


def build_create_cmd(exe_path: str) -> list[str]:
    return ["schtasks", "/Create", "/TN", TASK_NAME, "/SC", "ONLOGON",
            "/TR", exe_path, "/F"]


def build_delete_cmd() -> list[str]:
    return ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]


def build_query_cmd() -> list[str]:
    return ["schtasks", "/Query", "/TN", TASK_NAME]


def is_frozen_exe() -> bool:
    return bool(getattr(sys, "frozen", False))


def is_registered() -> bool:
    rc, _out, _err = run_hidden(build_query_cmd(), timeout=30.0)
    return rc == 0


def register(exe_path: str) -> dict:
    rc, out, err = run_hidden(build_create_cmd(exe_path), timeout=60.0)
    ok = rc == 0
    if not ok:
        logger.warning("注册开机自启失败 rc=%s: %s", rc, err[:200])
    return {"ok": ok, "registered": True, "detail": (out or err)[:300]}


def unregister() -> dict:
    if not is_registered():
        return {"ok": True, "registered": False, "detail": "本就未注册"}
    rc, out, err = run_hidden(build_delete_cmd(), timeout=60.0)
    ok = rc == 0
    return {"ok": ok, "registered": False,
            "detail": (out or err)[:300] if not ok else "已取消"}

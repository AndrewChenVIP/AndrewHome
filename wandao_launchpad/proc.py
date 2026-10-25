"""隐藏窗口子进程——全项目唯一的 subprocess 封装（单一实现铁律）。

返回 (rc, stdout, stderr)；超时抛 SubprocTimeout。
"""
from __future__ import annotations

import logging
import subprocess

logger = logging.getLogger(__name__)

_CREATE_NO_WINDOW = 0x08000000


class SubprocTimeout(Exception):
    pass


def run_hidden(cmd: list[str], timeout: float = 30.0, cwd: str | None = None,
               check: bool = False) -> tuple[int, str, str]:
    """跑命令不弹窗。stdout/stderr 按 utf-8 解码（errors=replace，不炸中文）。"""
    try:
        r = subprocess.run(
            cmd, capture_output=True, cwd=cwd, timeout=timeout,
            creationflags=_CREATE_NO_WINDOW if hasattr(subprocess, "STARTUPINFO") else 0,
        )
    except subprocess.TimeoutExpired as exc:
        raise SubprocTimeout(f"超时({timeout}s): {' '.join(cmd[:3])}…") from exc
    out = r.stdout.decode("utf-8", errors="replace").strip()
    err = r.stderr.decode("utf-8", errors="replace").strip()
    if check and r.returncode != 0:
        raise RuntimeError(f"命令失败 rc={r.returncode}: {' '.join(cmd)}\n{err}")
    if r.returncode != 0:
        logger.debug("子进程非零退出 rc=%s cmd=%s stderr=%s", r.returncode, cmd, err[:200])
    return r.returncode, out, err


def git(git_args: list[str], cwd: str | None = None,
        timeout: float = 60.0) -> tuple[int, str, str]:
    """git 子命令统一入口。"""
    return run_hidden(["git", *git_args], cwd=cwd, timeout=timeout)

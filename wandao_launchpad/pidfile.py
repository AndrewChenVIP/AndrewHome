"""pidfile——全项目唯一的跨进程协调实现（Mie 有两份逐行复制版，这里只许一份）。

教训对策（Mie 的 PID 复用误判）：
- 记录 create_time（进程创建时刻）。判活 = PID 存在 **且** create_time 吻合。
  机器重启后 PID 被无关进程复用时，create_time 对不上 → 正确判死。
- 原子写 + fsync。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

try:
    import psutil  # 声明式依赖，不是灰色软依赖
    _HAS_PSUTIL = True
except ImportError:  # pragma: no cover - 环境异常兜底
    psutil = None
    _HAS_PSUTIL = False


@dataclass
class PidRecord:
    pid: int
    port: int
    started_at: float          # epoch 秒，spawn 时刻（记录用）
    proc_create_time: float    # 目标进程的 create_time（判活用，防 PID 复用）
    log_path: str
    env_id: str


def read(path: Path) -> PidRecord | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        return PidRecord(
            pid=int(raw["pid"]),
            port=int(raw["port"]),
            started_at=float(raw.get("started_at", 0.0)),
            proc_create_time=float(raw.get("proc_create_time", 0.0)),
            log_path=str(raw.get("log_path", "")),
            env_id=str(raw.get("env_id", "")),
        )
    except FileNotFoundError:
        return None
    except (OSError, ValueError, KeyError):
        logger.warning("pidfile 损坏，视为不存在: %s", path, exc_info=True)
        return None


def is_alive(rec: PidRecord) -> bool:
    """PID 存在且创建时刻吻合（±2s 容忍时钟精度）才算活。"""
    if not _HAS_PSUTIL:
        # 无 psutil 时退化为存在性检查（Windows: kernel32 OpenProcess 由 psutil 提供，
        # 这里用 tasklist 探测太贵；直接保守返回 False 并记日志，由调用方走端口探测兜底）
        logger.debug("psutil 不可用，pidfile 判活退化为 False: pid=%s", rec.pid)
        return False
    if rec.pid <= 0:
        return False
    try:
        proc = psutil.Process(rec.pid)
        ct = proc.create_time()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.Error, OSError, ValueError):
        return False
    if rec.proc_create_time <= 0:
        return True  # 旧格式记录没有身份信息，只验存在
    return abs(ct - rec.proc_create_time) <= 2.0


def current_create_time(pid: int) -> float:
    """取进程 create_time；失败返回 0（记录里 0 = 不校验身份）。"""
    if not _HAS_PSUTIL:
        return 0.0
    try:
        return psutil.Process(pid).create_time()
    except (psutil.Error, OSError):
        return 0.0


def write(path: Path, rec: PidRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(asdict(rec), fh, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            logger.debug("pidfile 临时文件清理失败", exc_info=True)
        raise


def clear(path: Path) -> None:
    """只在本进程确认对方已死后清理；不存在不报错。"""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.debug("pidfile 清理失败: %s", path, exc_info=True)


def now() -> float:
    return time.time()

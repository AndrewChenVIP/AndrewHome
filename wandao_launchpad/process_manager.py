"""进程管理——ComfyUI 生命周期的唯一 owner。

教训对策（Mie 的三套并行实现 + UAC 误弹）：
- 杀进程一条链：优雅终止 → 等待验尸 → 仍活才 taskkill /F 一次 → 再验尸。
  绝不重复补刀已确认死亡的 PID，绝不做管理员提权（失败就如实报失败）。
- 绝不按端口扫描杀进程（会误杀无关进程）。
- start 幂等：pidfile 有活记录 → 拒绝并返回现有信息（退出码 2）。
- stop 幂等：没在跑 → no-op 成功。
"""

from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from . import pidfile
from .command_builder import build_argv, build_env
from .constants import (START_READY_TIMEOUT_SEC, STOP_FORCE_WAIT_SEC,
                        STOP_GRACEFUL_SEC)
from .context import AppContext
from .probe import probe, wait_ready

logger = logging.getLogger(__name__)

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:  # pragma: no cover
    psutil = None
    _HAS_PSUTIL = False

_CREATE_NO_WINDOW = 0x08000000  # Windows：子进程不弹控制台窗


@dataclass
class StartResult:
    started: bool          # 本次是否真的 spawn 了
    pid: int | None
    port: int
    url: str
    ready: bool
    elapsed_sec: float
    log_path: str | None
    error: str | None = None
    running_env_id: str = ""  # 拒绝启动时：当前占用者的环境 id


@dataclass
class StopResult:
    stopped: bool          # 是否真的杀掉了进程
    pid: int | None
    elapsed_sec: float
    error: str | None = None


class ProcessManager:
    def __init__(self, ctx: AppContext, pidfile_path: Path):
        self.ctx = ctx
        self.pidfile_path = pidfile_path
        self._proc: subprocess.Popen | None = None  # 本进程亲手 spawn 的句柄

    # ---------- 内部工具 ----------

    def _running_record(self) -> pidfile.PidRecord | None:
        rec = pidfile.read(self.pidfile_path)
        if rec and pidfile.is_alive(rec):
            return rec
        if rec:
            logger.info("pidfile 记录 PID=%s 已死，清理", rec.pid)
            pidfile.clear(self.pidfile_path)
        return None

    # ---------- start ----------

    def start(self, wait_timeout: float = START_READY_TIMEOUT_SEC,
              no_wait: bool = False) -> StartResult:
        t0 = time.monotonic()
        url = self.ctx.base_url
        base = StartResult(started=False, pid=None, port=self.ctx.port, url=url,
                           ready=False, elapsed_sec=0.0, log_path=None)

        existing = self._running_record()
        if existing is not None:
            base.running_env_id = existing.env_id
            base.error = f"已有实例在跑: PID={existing.pid} (env={existing.env_id})"
            base.elapsed_sec = time.monotonic() - t0
            return base

        errs = self.ctx.launch.validate()
        if errs:
            base.error = "启动选项非法: " + "; ".join(errs)
            base.elapsed_sec = time.monotonic() - t0
            return base

        argv = build_argv(self.ctx)
        env = build_env(self.ctx)
        log_path = self.ctx.comfyui_log
        log_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("启动: %s", " ".join(argv))

        creationflags = _CREATE_NO_WINDOW if hasattr(subprocess, "STARTUPINFO") else 0
        with open(log_path, "ab") as log_fh:
            self._proc = subprocess.Popen(
                argv, env=env, stdout=log_fh, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, creationflags=creationflags,
            )
        pid = self._proc.pid
        pidfile.write(self.pidfile_path, pidfile.PidRecord(
            pid=pid, port=self.ctx.port, started_at=pidfile.now(),
            proc_create_time=pidfile.current_create_time(pid),
            log_path=str(log_path), env_id=self.ctx.env.id,
        ))

        base.started = True
        base.pid = pid
        base.log_path = str(log_path)
        if no_wait:
            base.ready = probe(url)
            base.elapsed_sec = time.monotonic() - t0
            return base

        base.ready = wait_ready(url, deadline_sec=wait_timeout)
        base.elapsed_sec = time.monotonic() - t0
        if not base.ready:
            base.error = f"{wait_timeout:.0f}s 内 /system_stats 未就绪"
            # 不回滚进程：ComfyUI 可能仍在慢启动（模型预热），交给用户决定 stop
        return base

    # ---------- stop ----------

    def stop(self, graceful_sec: float = STOP_GRACEFUL_SEC) -> StopResult:
        t0 = time.monotonic()
        rec = self._running_record()
        if rec is None:
            return StopResult(stopped=False, pid=None,
                              elapsed_sec=time.monotonic() - t0)

        pid = rec.pid
        ok = self._terminate_chain(pid, graceful_sec)
        pidfile.clear(self.pidfile_path)
        elapsed = time.monotonic() - t0
        if not ok:
            return StopResult(stopped=False, pid=pid, elapsed_sec=elapsed,
                              error=f"PID={pid} 终止失败（权限不足或系统拒绝）")
        return StopResult(stopped=True, pid=pid, elapsed_sec=elapsed)

    def _terminate_chain(self, pid: int, graceful_sec: float) -> bool:
        """一条链：优雅 → 验尸 → 强杀一次 → 验尸。中途确认死亡立即返回。"""
        # 1) 优雅终止
        if _HAS_PSUTIL:
            try:
                proc = psutil.Process(pid)
                proc.terminate()
                try:
                    proc.wait(timeout=graceful_sec)
                    logger.info("优雅终止成功: PID=%s", pid)
                    return True
                except psutil.TimeoutExpired:
                    logger.debug("优雅终止超时 PID=%s，转强杀", pid)
            except psutil.NoSuchProcess:
                logger.info("终止前进程已消失: PID=%s", pid)
                return True
            except psutil.AccessDenied:
                logger.warning("psutil 无权限终止 PID=%s，转强杀", pid)
            except psutil.Error:
                logger.warning("psutil 终止异常 PID=%s，转强杀", pid, exc_info=True)

        # 2) 强杀：taskkill /T /F 一次（/T 连子进程树；不对已死进程补刀）
        if not _pid_exists(pid):
            logger.info("强杀前进程已消失: PID=%s", pid)
            return True
        try:
            r = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                capture_output=True, text=True, timeout=15,
                creationflags=_CREATE_NO_WINDOW if hasattr(subprocess, "STARTUPINFO") else 0,
            )
            if r.returncode != 0:
                logger.warning("taskkill PID=%s rc=%s stdout=%s stderr=%s",
                               pid, r.returncode, r.stdout.strip(), r.stderr.strip())
        except (OSError, subprocess.TimeoutExpired):
            logger.warning("taskkill 执行失败 PID=%s", pid, exc_info=True)

        # 3) 验尸（有上限地等）
        deadline = time.monotonic() + STOP_FORCE_WAIT_SEC
        while time.monotonic() < deadline:
            if not _pid_exists(pid):
                logger.info("强杀确认死亡: PID=%s", pid)
                return True
            time.sleep(0.2)
        return not _pid_exists(pid)

    # ---------- status ----------

    def status(self) -> dict:
        import datetime

        rec = pidfile.read(self.pidfile_path)
        alive = pidfile.is_alive(rec) if rec else False
        if rec and not alive:
            pidfile.clear(self.pidfile_path)
            rec = None
        running = probe(self.ctx.base_url) if rec else False
        since = None
        if rec and rec.started_at > 0:
            since = datetime.datetime.fromtimestamp(
                rec.started_at, tz=datetime.timezone.utc).isoformat()
        return {
            "running": running,
            "http_reachable": running,
            "pid": rec.pid if rec else None,
            "port": self.ctx.port,
            "url": self.ctx.base_url,
            "log_path": rec.log_path if rec else str(self.ctx.comfyui_log),
            "since": since,
            "env_id": rec.env_id if rec else None,
        }


def _pid_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    if _HAS_PSUTIL:
        return psutil.pid_exists(pid)
    # 兜底：Windows tasklist（慢，但只在无 psutil 的退化路径走到）
    try:
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                           capture_output=True, text=True, timeout=10,
                           creationflags=_CREATE_NO_WINDOW if hasattr(subprocess, "STARTUPINFO") else 0)
        return str(pid) in r.stdout
    except (OSError, subprocess.TimeoutExpired):
        logger.warning("tasklist 探测失败 pid=%s", pid, exc_info=True)
        return False

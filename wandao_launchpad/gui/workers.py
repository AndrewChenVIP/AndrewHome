"""GUI 后台 worker——所有重活（spawn/stop/探测/日志tail）都在线程里，主线程只收信号。

教训对策（Mie 主线程跑依赖检查卡 UI 24s、UiInvoker 吞异常致按钮永久禁用）：
- 每个 worker 结束必发 finished(ok, payload)——成功失败都通知，异常兜住并带出来。
- worker 不碰任何 UI 控件。
"""

from __future__ import annotations

import logging
import time

from PyQt5 import QtCore

from ..config import ConfigStore
from ..constants import pidfile_path
from ..context import build_context
from ..process_manager import ProcessManager
from ..probe import probe

logger = logging.getLogger(__name__)


class _Worker(QtCore.QThread):
    finished_sig = QtCore.pyqtSignal(bool, dict)

    def _done(self, ok: bool, payload: dict) -> None:
        self.finished_sig.emit(ok, payload)


class FunctionWorker(_Worker):
    """通用后台执行器：任意可调用 → (ok, payload)。异常兜住并带出来。"""

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            payload = self._fn()
            ok = not (isinstance(payload, dict) and payload.get("ok") is False)
            self._done(ok, payload if isinstance(payload, dict) else {"result": payload})
        except Exception as exc:  # noqa: BLE001 —— worker 边界必须兜底并上报
            logger.error("FunctionWorker 异常", exc_info=True)
            self._done(False, {"error": str(exc)})


class StartWorker(_Worker):
    def __init__(self, store: ConfigStore, parent=None):
        super().__init__(parent)
        self.store = store

    def run(self) -> None:
        try:
            cfg = self.store.load()
            ctx = build_context(cfg)
            # 启动前体检（quick：无子进程快检查）——fail 级问题直接拦截
            from .. import doctor
            checks = doctor.run_checks(ctx, quick=True)
            fails = doctor.blockers(checks)
            if fails:
                self._done(False, {"preflight": True, "error": "体检未通过",
                                   "checks": checks, "fail": fails})
                return
            pm = ProcessManager(ctx, pidfile_path(self.store.config_dir))
            res = pm.start(wait_timeout=180.0)
            self._done(res.started and res.ready, {
                "started": res.started, "ready": res.ready, "pid": res.pid,
                "url": res.url, "error": res.error,
                "already_running": bool(res.running_env_id),
                "external": res.external,
            })
        except Exception as exc:  # noqa: BLE001 —— worker 边界必须兜底并上报
            logger.error("StartWorker 异常", exc_info=True)
            self._done(False, {"error": str(exc)})


class StopWorker(_Worker):
    def __init__(self, store: ConfigStore, parent=None):
        super().__init__(parent)
        self.store = store

    def run(self) -> None:
        try:
            cfg = self.store.load()
            ctx = build_context(cfg)
            pm = ProcessManager(ctx, pidfile_path(self.store.config_dir))
            res = pm.stop()
            self._done(res.stopped or res.pid is None,
                       {"stopped": res.stopped, "pid": res.pid, "error": res.error})
        except Exception as exc:  # noqa: BLE001
            logger.error("StopWorker 异常", exc_info=True)
            self._done(False, {"error": str(exc)})


class StatusWorker(_Worker):
    """单次状态探测（由主窗口定时器按需触发，不做常驻轮询循环）。"""

    def __init__(self, store: ConfigStore, parent=None):
        super().__init__(parent)
        self.store = store

    def run(self) -> None:
        try:
            cfg = self.store.load()
            ctx = build_context(cfg)
            pm = ProcessManager(ctx, pidfile_path(self.store.config_dir))
            st = pm.status()
            self._done(True, st)
        except Exception as exc:  # noqa: BLE001
            logger.error("StatusWorker 异常", exc_info=True)
            self._done(False, {"error": str(exc)})


class LogTailWorker(_Worker):
    """跟随日志文件追加。批量（≤0.3s / ≤200 行）发射，避免逐行刷屏。"""

    batch_sig = QtCore.pyqtSignal(list)
    rotated_sig = QtCore.pyqtSignal()

    def __init__(self, log_path: str, parent=None):
        super().__init__(parent)
        self.log_path = log_path
        self._stop_flag = False

    def stop(self) -> None:
        self._stop_flag = True

    def run(self) -> None:
        import os

        path = self.log_path
        try:
            fh = open(path, "rb", buffering=0)
        except OSError:
            self._done(False, {"error": f"打不开日志: {path}"})
            return
        with fh:
            fh.seek(0, 2)  # 从尾部开始
            last_size = fh.tell()
            while not self._stop_flag:
                line = fh.readline()
                if line:
                    batch = [line.decode("utf-8", errors="replace").rstrip("\r\n")]
                    deadline = time.monotonic() + 0.3
                    while (len(batch) < 200 and time.monotonic() < deadline
                           and not self._stop_flag):
                        nl = fh.readline()
                        if not nl:
                            break
                        batch.append(nl.decode("utf-8", errors="replace").rstrip("\r\n"))
                    self.batch_sig.emit(batch)
                    last_size = fh.tell()
                    continue
                # 无新内容：检查轮转/截断
                try:
                    cur = os.path.getsize(path)
                except OSError:
                    cur = last_size
                if cur < last_size:
                    fh.seek(0)
                    last_size = 0
                    self.rotated_sig.emit()
                self.msleep(300)
        self._done(True, {})

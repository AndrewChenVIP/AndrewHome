"""内核版本页——版本卡片 + 更新（ff-only/稳定版） + 提交历史/切换。"""

from __future__ import annotations

from PyQt5 import QtCore, QtWidgets

from ..config import ConfigStore
from ..context import build_context
from ..kernel import KernelService
from .workers import FunctionWorker

PAGE_SIZE = 50


class KernelPage(QtWidgets.QWidget):
    def __init__(self, store: ConfigStore, status_cb=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.status_cb = status_cb or (lambda msg: None)
        self._worker = None
        self._skip = 0

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("内核版本管理")
        title.setObjectName("title")
        head.addWidget(title)
        head.addStretch(1)
        lay.addLayout(head)

        info_box = QtWidgets.QGroupBox("当前版本")
        ib = QtWidgets.QVBoxLayout(info_box)
        self.info_label = QtWidgets.QLabel("（未读取）")
        self.info_label.setObjectName("muted")
        ib.addWidget(self.info_label)
        row = QtWidgets.QHBoxLayout()
        self.stable_only = QtWidgets.QCheckBox("仅更新到稳定版标签")
        row.addWidget(self.stable_only)
        self.sync_deps = QtWidgets.QCheckBox("同步依赖库（torch 系冻结不动）")
        row.addWidget(self.sync_deps)
        btn_update = QtWidgets.QPushButton("更新内核")
        btn_update.setObjectName("primary")
        btn_update.clicked.connect(self.update_kernel)
        row.addWidget(btn_update)
        btn_refresh = QtWidgets.QPushButton("刷新")
        btn_refresh.clicked.connect(self.reload)
        row.addWidget(btn_refresh)
        row.addStretch(1)
        ib.addLayout(row)
        lay.addWidget(info_box)

        hist_box = QtWidgets.QGroupBox("提交历史（选中任意提交可切换过去）")
        hb = QtWidgets.QVBoxLayout(hist_box)
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["哈希", "日期", "作者", "说明"])
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 90)
        self.table.setColumnWidth(1, 150)
        self.table.setColumnWidth(2, 140)
        hb.addWidget(self.table)
        nav = QtWidgets.QHBoxLayout()
        self.btn_prev = QtWidgets.QPushButton("上一页")
        self.btn_prev.clicked.connect(lambda: self.load_log(-PAGE_SIZE))
        self.btn_next = QtWidgets.QPushButton("下一页")
        self.btn_next.clicked.connect(lambda: self.load_log(PAGE_SIZE))
        self.btn_checkout = QtWidgets.QPushButton("切换到所选提交…")
        self.btn_checkout.clicked.connect(self.checkout_selected)
        nav.addWidget(self.btn_prev)
        nav.addWidget(self.btn_next)
        nav.addStretch(1)
        nav.addWidget(self.btn_checkout)
        hb.addLayout(nav)
        lay.addWidget(hist_box)

    def _svc(self, for_write=False) -> KernelService:
        cfg = self.store.load()
        ctx = build_context(cfg)
        return KernelService(ctx.comfyui_root / "ComfyUI",
                             base_url=ctx.base_url if for_write else None,
                             github_proxy=cfg.mirrors.github_proxy)

    def _run(self, fn, on_done):
        self._worker = FunctionWorker(fn, self)
        self._worker.finished_sig.connect(on_done)
        self._worker.start()

    # ---------- 版本 ----------

    def reload(self) -> None:
        def job():
            info = self._svc().info()
            return {"ok": True, "info": info.__dict__}
        self._run(job, self._on_info)

    def _on_info(self, ok: bool, payload: dict) -> None:
        if not ok:
            self.info_label.setText(f"读取失败: {payload.get('error')}")
            return
        info = payload["info"]
        self.info_label.setText(
            f"ComfyUI {info['comfyui_version']}  ·  {info['commit']}  ·  "
            f"{info['commit_date'][:10]}  ·  {info['commit_subject'][:50]}"
            + ("  ⚠ 有未提交改动" if info["dirty"] else ""))
        self.status_cb("内核版本已刷新")
        self.load_log(0)

    def update_kernel(self) -> None:
        stable = self.stable_only.isChecked()
        if QtWidgets.QMessageBox.question(
                self, "更新内核",
                "更新 ComfyUI 内核（fast-forward only，运行中/脏树会拒绝）"
                f"{'，目标：最新稳定版标签' if stable else ''}？") \
                != QtWidgets.QMessageBox.Yes:
            return

        def job():
            result = {"ok": True,
                      **self._svc(for_write=True).update(stable_only=stable)}
            if result.get("updated") and self.sync_deps.isChecked():
                from .. import pipx
                from ..network import pip_index_url
                cfg = self.store.load()
                ctx = build_context(cfg)
                result["deps"] = pipx.sync_comfy_requirements(
                    ctx.comfyui_root / "ComfyUI", ctx.python_exe,
                    index_url=pip_index_url(cfg.mirrors.pypi))
            return result
        self.status_cb("更新内核（fetch 可能较慢）…")
        self._run(job, self._on_updated)

    def _on_updated(self, ok: bool, payload: dict) -> None:
        if not ok:
            QtWidgets.QMessageBox.warning(self, "更新失败", str(payload.get("error")))
            self.status_cb(f"内核更新失败: {payload.get('error')}")
            return
        deps = payload.get("deps") or {}
        if deps.get("ran"):
            note = "，依赖已同步" if deps.get("ok") else "，依赖同步失败（CUDA 栈未动）"
        else:
            note = ""
        if not payload.get("updated"):
            self.status_cb(f"内核已是最新（{payload.get('to')}）")
        else:
            self.status_cb(f"内核已更新 → {payload.get('to')}{note}")
        self.reload()

    # ---------- 历史 ----------

    def load_log(self, delta: int) -> None:
        self._skip = max(0, self._skip + delta)

        def job():
            rows = self._svc().log(count=PAGE_SIZE, skip=self._skip)
            return {"ok": True, "rows": rows, "skip": self._skip}
        self._run(job, self._on_log)

    def _on_log(self, ok: bool, payload: dict) -> None:
        if not ok:
            self.status_cb(f"历史读取失败: {payload.get('error')}")
            return
        self.table.setRowCount(0)
        for r in payload["rows"]:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col, key in enumerate(("commit", "date", "author", "subject")):
                item = QtWidgets.QTableWidgetItem(str(r[key])[:80])
                if col == 0:
                    item.setData(QtCore.Qt.UserRole, r["commit"])
                self.table.setItem(row, col, item)
        self.status_cb(f"提交历史：第 {payload['skip'] + 1}–"
                       f"{payload['skip'] + len(payload['rows'])} 条")

    def checkout_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return
        ref = self.table.item(rows[0].row(), 0).data(QtCore.Qt.UserRole)
        if QtWidgets.QMessageBox.warning(
                self, "切换内核版本",
                f"git checkout 到 {ref}？（运行中/脏树会拒绝；回到最新用「更新内核」）",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
            return

        def job():
            return {"ok": True, "checked_out": self._svc(for_write=True).checkout(ref)}
        self.status_cb(f"切换到 {ref}…")
        self._run(job, self._on_checked)

    def _on_checked(self, ok: bool, payload: dict) -> None:
        self.status_cb(f"已切换到 {payload.get('checked_out')}" if ok
                       else f"切换失败: {payload.get('error')}")
        self.reload()

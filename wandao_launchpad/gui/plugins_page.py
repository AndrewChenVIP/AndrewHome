"""插件管理页——列表/启停/并行检查更新/更新全部。重活全走 FunctionWorker。"""

from __future__ import annotations

from PyQt5 import QtCore, QtWidgets

from ..config import ConfigStore
from ..context import build_context
from ..plugins import PluginService
from .workers import FunctionWorker

_COLS = ["插件", "类型", "状态", "更新"]


class PluginsPage(QtWidgets.QWidget):
    def __init__(self, store: ConfigStore, status_cb=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.status_cb = status_cb or (lambda msg: None)
        self._worker = None
        self._plugins: list = []

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("插件管理")
        title.setObjectName("title")
        self.count_label = QtWidgets.QLabel("")
        self.count_label.setObjectName("muted")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.count_label)
        lay.addLayout(head)

        bar = QtWidgets.QHBoxLayout()
        for text, fn in (("刷新", self.reload), ("检查更新", self.check_updates),
                         ("更新全部", self.update_all),
                         ("🔍 搜索安装…", self.search_install)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        for text, fn in (("启用选中", lambda: self.set_selected(True)),
                         ("禁用选中", lambda: self.set_selected(False)),
                         ("卸载选中…", self.uninstall_selected)):
            b = QtWidgets.QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        bar.addStretch(1)
        lay.addLayout(bar)

        self.table = QtWidgets.QTableWidget(0, len(_COLS))
        self.table.setHorizontalHeaderLabels(_COLS)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 320)
        lay.addWidget(self.table)

    # ---------- 基础 ----------

    def _svc(self) -> PluginService:
        cfg = self.store.load()
        from ..context import build_context
        ctx = build_context(cfg)
        return PluginService(ctx.comfyui_root / "ComfyUI" / "custom_nodes",
                             cache_dir=self.store.config_dir,
                             github_proxy=cfg.mirrors.github_proxy)

    def _run(self, fn, on_done):
        self._worker = FunctionWorker(fn, self)
        self._worker.finished_sig.connect(on_done)
        self._worker.start()

    def reload(self) -> None:
        def job():
            items = self._svc().list()
            return {"ok": True, "plugins": [p.__dict__ for p in items]}
        self.status_cb("扫描插件…")
        self._run(job, self._on_loaded)

    def _on_loaded(self, ok: bool, payload: dict) -> None:
        if not ok:
            self.status_cb(f"扫描失败: {payload.get('error')}")
            return
        self._plugins = payload["plugins"]
        self._fill({})
        n_git = sum(1 for p in self._plugins if p["is_git"])
        n_off = sum(1 for p in self._plugins if not p["enabled"])
        self.count_label.setText(f"共 {len(self._plugins)} · git {n_git} · 停用 {n_off}")
        self.status_cb("插件列表已刷新")

    def _fill(self, updates: dict) -> None:
        self.table.setRowCount(0)
        for p in self._plugins:
            row = self.table.rowCount()
            self.table.insertRow(row)
            state = "✅ 启用" if p["enabled"] else "⛔ 停用"
            upinfo = updates.get(p["dir_name"])
            up_txt = "—" if upinfo is None else ("🔄 可更新" if upinfo else "最新")
            for col, text in enumerate((p["name"], "git" if p["is_git"] else "本地",
                                        state, up_txt)):
                item = QtWidgets.QTableWidgetItem(text)
                if col == 0:
                    item.setData(QtCore.Qt.UserRole, p["dir_name"])
                self.table.setItem(row, col, item)

    def _selected_dir_names(self) -> list[str]:
        return [self.table.item(idx.row(), 0).data(QtCore.Qt.UserRole)
                for idx in self.table.selectionModel().selectedRows()]

    # ---------- 动作 ----------

    def search_install(self) -> None:
        """搜索官方插件清单并安装（输入 git URL 则直接 clone），自动装依赖。"""
        text, ok = QtWidgets.QInputDialog.getText(
            self, "搜索安装插件",
            "输入插件名（搜官方清单）或 git URL：")
        if not ok or not text.strip():
            return
        target = text.strip()
        label = target if target.startswith("http") else f"名称「{target}」匹配的插件"

        def job():
            info = self._svc().install(target)
            deps = self._ensure_deps(info.dir_name)
            return {"ok": True, "plugin": info.__dict__, "deps": deps}
        self.status_cb(f"安装 {label}（clone+依赖，稍候）…")
        self._run(job, lambda ok_, p: self._on_installed(p, ok_))

    def _ensure_deps(self, dir_name: str) -> dict:
        """装插件 requirements（无文件则跳过）。失败不中断。"""
        from .. import pipx
        from ..network import pip_index_url
        try:
            ctx = build_context(self.store.load())
            return pipx.ensure_requirements(
                self._svc().dir / dir_name, ctx.python_exe,
                index_url=pip_index_url(self.store.load().mirrors.pypi))
        except Exception as exc:  # noqa: BLE001 —— 依赖失败不拖垮安装结果
            return {"ran": True, "ok": False, "log": "", "reason": str(exc)}

    def _on_installed(self, payload: dict, ok: bool) -> None:
        if ok:
            name = payload.get("plugin", {}).get("dir_name", "")
            deps = payload.get("deps") or {}
            note = ""
            if deps.get("ran") and deps.get("ok") is False:
                note = "（依赖安装失败，见日志）"
            elif deps.get("ran"):
                note = "（依赖已装）"
            self.status_cb(f"已安装 {name}{note}")
        else:
            QtWidgets.QMessageBox.warning(self, "安装失败", str(payload.get("error")))
            self.status_cb(f"安装失败: {payload.get('error')}")
        self.reload()

    def check_updates(self) -> None:
        def job():
            results = self._svc().check_updates()
            return {"ok": True, "results": results}
        self.status_cb("并行检查更新（git 网络操作，稍候）…")
        self._run(job, self._on_checked)

    def _on_checked(self, ok: bool, payload: dict) -> None:
        if not ok:
            self.status_cb(f"检查失败: {payload.get('error')}")
            return
        updates = {r["dir_name"]: r["outdated"] for r in payload["results"]
                   if r["outdated"] is not None}
        self._fill(updates)
        n = sum(1 for v in updates.values() if v)
        self.status_cb(f"检查完成：{n} 个可更新")

    def update_all(self) -> None:
        if QtWidgets.QMessageBox.question(
                self, "更新全部", "更新全部 git 插件（干净树 pull --ff-only）？") \
                != QtWidgets.QMessageBox.Yes:
            return

        def job():
            results = self._svc().update_all()
            dep_note = 0
            for r in results:
                if r.get("ok") and r.get("changed"):
                    deps = self._ensure_deps(r["dir_name"])
                    r["deps"] = deps
                    if deps.get("ran"):
                        dep_note += 1
            return {"ok": True, "results": results, "deps_done": dep_note}
        self.status_cb("更新全部插件…")
        self._run(job, self._on_updated)

    def _on_updated(self, ok: bool, payload: dict) -> None:
        results = payload.get("results", [])
        done = sum(1 for r in results if r["ok"])
        skip = sum(1 for r in results if r["skipped"])
        dep_note = payload.get("deps_done", 0)
        dep_txt = f"，依赖安装 {dep_note}" if dep_note else ""
        self.status_cb(f"插件更新完成 {done}/{len(results)}（跳过 {skip}{dep_txt}）")
        self.reload()

    def set_selected(self, enable: bool) -> None:
        names = self._selected_dir_names()
        if not names:
            return

        def job():
            svc = self._svc()
            for name in names:
                svc.set_enabled(name, enable)
            return {"ok": True, "count": len(names)}
        self.status_cb(("启用" if enable else "禁用") + f" {len(names)} 个插件…")
        self._run(job, lambda ok, p: (self.status_cb("完成") if ok
                                      else self.status_cb(f"失败: {p.get('error')}"),
                                      self.reload()))

    def uninstall_selected(self) -> None:
        names = self._selected_dir_names()
        if not names:
            return
        if QtWidgets.QMessageBox.warning(
                self, "卸载确认", f"将删除 {len(names)} 个插件目录（不可恢复）：\n"
                + "\n".join(names[:8]) + ("…" if len(names) > 8 else ""),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No) != QtWidgets.QMessageBox.Yes:
            return

        def job():
            svc = self._svc()
            for name in names:
                svc.uninstall(name)
            return {"ok": True, "count": len(names)}
        self.status_cb(f"卸载 {len(names)} 个插件…")
        self._run(job, lambda ok, p: (self.status_cb("已卸载") if ok
                                      else self.status_cb(f"失败: {p.get('error')}"),
                                      self.reload()))

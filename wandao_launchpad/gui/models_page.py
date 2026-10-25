"""外置模型库页——左库列表右编辑，应用时渲染 extra_model_paths.yaml（先备份）。"""

from __future__ import annotations

from PyQt5 import QtCore, QtWidgets

from ..config import ConfigStore
from ..context import build_context
from ..model_paths import ModelLibrary, ModelPathsService
from .workers import FunctionWorker


class ModelsPage(QtWidgets.QWidget):
    def __init__(self, store: ConfigStore, status_cb=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.status_cb = status_cb or (lambda msg: None)
        self._worker = None
        self._libs: list[ModelLibrary] = []
        self._current: int = -1

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("外置模型库")
        title.setObjectName("title")
        hint = QtWidgets.QLabel("模型留在原处，挂载进 ComfyUI（extra_model_paths.yaml）")
        hint.setObjectName("muted")
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(hint)
        lay.addLayout(head)

        body = QtWidgets.QHBoxLayout()
        # 左：库列表
        left = QtWidgets.QVBoxLayout()
        self.list = QtWidgets.QListWidget()
        self.list.currentRowChanged.connect(self._on_select)
        left.addWidget(self.list)
        lbtns = QtWidgets.QHBoxLayout()
        b_add = QtWidgets.QPushButton("添加库")
        b_add.clicked.connect(self.add_lib)
        b_del = QtWidgets.QPushButton("移除所选")
        b_del.clicked.connect(self.remove_lib)
        lbtns.addWidget(b_add)
        lbtns.addWidget(b_del)
        left.addLayout(lbtns)
        body.addLayout(left, 1)

        # 右：编辑
        right = QtWidgets.QVBoxLayout()
        form = QtWidgets.QGridLayout()
        form.addWidget(QtWidgets.QLabel("名称"), 0, 0)
        self.ed_name = QtWidgets.QLineEdit()
        form.addWidget(self.ed_name, 0, 1)
        form.addWidget(QtWidgets.QLabel("目录"), 1, 0)
        path_row = QtWidgets.QHBoxLayout()
        self.ed_path = QtWidgets.QLineEdit()
        btn_browse = QtWidgets.QPushButton("浏览…")
        btn_browse.clicked.connect(self._browse)
        path_row.addWidget(self.ed_path)
        path_row.addWidget(btn_browse)
        form.addLayout(path_row, 1, 1)
        self.cb_enabled = QtWidgets.QCheckBox("启用")
        form.addWidget(self.cb_enabled, 2, 0)
        self.cb_default = QtWidgets.QCheckBox("设为默认库（★）")
        form.addWidget(self.cb_default, 2, 1)
        right.addLayout(form)

        self.mappings_label = QtWidgets.QLabel("映射预览：")
        self.mappings_label.setObjectName("muted")
        self.mappings_label.setWordWrap(True)
        right.addWidget(self.mappings_label)
        right.addStretch(1)

        rbtns = QtWidgets.QHBoxLayout()
        b_apply = QtWidgets.QPushButton("应用更改（写 yaml，旧文件先备份）")
        b_apply.setObjectName("primary")
        b_apply.clicked.connect(self.apply)
        b_import = QtWidgets.QPushButton("导入现有 yaml")
        b_import.clicked.connect(self.import_existing)
        b_check = QtWidgets.QPushButton("体检")
        b_check.clicked.connect(self.validate)
        rbtns.addWidget(b_apply)
        rbtns.addWidget(b_import)
        rbtns.addWidget(b_check)
        right.addLayout(rbtns)
        body.addLayout(right, 2)
        lay.addLayout(body, 1)

        QtCore.QTimer.singleShot(0, self.reload)

    def _svc(self) -> ModelPathsService:
        ctx = build_context(self.store.load())
        return ModelPathsService(ctx.comfyui_root / "ComfyUI", self.store.config_dir)

    def _run(self, fn, on_done):
        self._worker = FunctionWorker(fn, self)
        self._worker.finished_sig.connect(on_done)
        self._worker.start()

    # ---------- 列表与编辑 ----------

    def reload(self) -> None:
        def job():
            svc = self._svc()
            svc.import_existing()  # 首次自动导入（sidecar 空且 yaml 存在时）
            return {"ok": True,
                    "libs": [l.__dict__ for l in svc.load_libraries()],
                    "maps": {l.id: svc.effective_mappings(l)
                             for l in svc.load_libraries()}}
        self._run(job, self._on_loaded)

    def _on_loaded(self, ok: bool, payload: dict) -> None:
        if not ok:
            self.status_cb(f"模型库读取失败: {payload.get('error')}")
            return
        self._libs = [ModelLibrary(**d) for d in payload["libs"]]
        self._maps = payload["maps"]
        self.list.blockSignals(True)
        self.list.clear()
        for lib in self._libs:
            star = "★ " if lib.is_default else ""
            off = "（停用）" if not lib.enabled else ""
            self.list.addItem(f"{star}{lib.name}{off}")
        self.list.blockSignals(False)
        if self._libs:
            self.list.setCurrentRow(0)
        self.status_cb(f"模型库 {len(self._libs)} 个")

    def _on_select(self, row: int) -> None:
        self._current = row
        if not (0 <= row < len(self._libs)):
            return
        lib = self._libs[row]
        self.ed_name.setText(lib.name)
        self.ed_path.setText(lib.base_path)
        self.cb_enabled.setChecked(lib.enabled)
        self.cb_default.setChecked(lib.is_default)
        maps = self._maps.get(lib.id, {})
        self.mappings_label.setText(
            "映射预览：" + (", ".join(f"{k}→{v}" for k, v in maps.items()) or "（目录下无已知类型子目录）"))

    def _write_back_current(self) -> None:
        """把右侧表单写回当前选中项（切行/应用前调用）。"""
        if not (0 <= self._current < len(self._libs)):
            return
        lib = self._libs[self._current]
        lib.name = self.ed_name.text().strip() or lib.name
        lib.base_path = self.ed_path.text().strip()
        lib.enabled = self.cb_enabled.isChecked()
        lib.is_default = self.cb_default.isChecked()

    def add_lib(self) -> None:
        self._write_back_current()
        lib = ModelLibrary(id=f"lib_{len(self._libs)}_{id(self) % 10000}",
                           name="新模型库", base_path="", enabled=True)
        self._libs.append(lib)
        self._on_loaded(True, {"libs": [l.__dict__ for l in self._libs],
                               "maps": self._maps})

    def remove_lib(self) -> None:
        if not (0 <= self._current < len(self._libs)):
            return
        name = self._libs[self._current].name
        if QtWidgets.QMessageBox.question(
                self, "移除库", f"从挂载列表移除「{name}」？（不动磁盘文件，只取消挂载）") \
                != QtWidgets.QMessageBox.Yes:
            return
        self._libs.pop(self._current)
        self._current = -1
        self._on_loaded(True, {"libs": [l.__dict__ for l in self._libs],
                               "maps": self._maps})

    def _browse(self) -> None:
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "选择模型库目录")
        if d:
            self.ed_path.setText(d)

    # ---------- 动作 ----------

    def apply(self) -> None:
        self._write_back_current()

        def job():
            svc = self._svc()
            svc.save_libraries(self._libs)
            return {"ok": True, **svc.apply()}
        self.status_cb("渲染 extra_model_paths.yaml…")
        self._run(job, self._on_applied)

    def _on_applied(self, ok: bool, payload: dict) -> None:
        if not ok:
            QtWidgets.QMessageBox.warning(self, "应用失败", str(payload.get("error")))
            return
        self.status_cb(f"已写 {payload.get('libraries')} 库 / "
                       f"{payload.get('mappings')} 映射"
                       + (f"（备份: {payload.get('backup')}）" if payload.get("backup") else ""))

    def import_existing(self) -> None:
        def job():
            return {"ok": True, "imported": self._svc().import_existing()}
        self._run(job, lambda ok, p: self.reload())

    def validate(self) -> None:
        self._write_back_current()

        def job():
            svc = self._svc()
            svc.save_libraries(self._libs)
            return {"ok": True, "problems": svc.validate()}
        self._run(job, self._on_validated)

    def _on_validated(self, ok: bool, payload: dict) -> None:
        problems = payload.get("problems", [])
        if not problems:
            self.status_cb("体检通过：路径与映射全部有效")
        else:
            QtWidgets.QMessageBox.information(
                self, "体检结果", "\n".join(problems[:20])
                + ("…" if len(problems) > 20 else ""))
            self.status_cb(f"体检发现 {len(problems)} 个问题")

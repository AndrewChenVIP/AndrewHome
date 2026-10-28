"""出图归档页——缩略图网格勾选，图像/视频两区，一键只增不删拷进 NAS 作品库。"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from PyQt5 import QtCore, QtWidgets

from ..archive import (DEFAULT_ARCHIVE_TARGET, DEFAULT_VIDEO_TARGET,
                       IMAGE_EXTS, VIDEO_EXTS, archive_files,
                       list_recent_outputs, output_dir_of)
from ..config import ConfigStore
from ..context import build_context
from .workers import FunctionWorker, ThumbWorker

_KINDS = [("图像", "image", IMAGE_EXTS, "archive_target", "last_archive_at"),
          ("视频", "video", VIDEO_EXTS, "archive_video_target", "last_archive_video_at")]

_COLS = ["文件", "大小", "修改时间"]


def _fmt_size(n: int) -> str:
    if n >= 1024**3:
        return f"{n / 1024**3:.2f} GB"
    if n >= 1024**2:
        return f"{n / 1024**2:.1f} MB"
    return f"{n / 1024:.0f} KB"


class ArchivePage(QtWidgets.QWidget):
    def __init__(self, store: ConfigStore, status_cb=None, parent=None):
        super().__init__(parent)
        self.store = store
        self.status_cb = status_cb or (lambda msg: None)
        self._worker = None
        self._thumb_worker = None
        self._items: list[dict] = []
        self._bulk = False  # 批量勾选时不逐项刷计数

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(20, 16, 20, 16)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("出图归档")
        title.setObjectName("title")
        head.addWidget(title)
        self.kind_combo = QtWidgets.QComboBox()
        for label, _kind, _exts, _t, _w in _KINDS:
            self.kind_combo.addItem(label, label)
        self.kind_combo.currentIndexChanged.connect(lambda _: self.reload())
        head.addWidget(self.kind_combo)
        head.addStretch(1)
        self.target_label = QtWidgets.QLabel("")
        self.target_label.setObjectName("muted")
        head.addWidget(self.target_label)
        lay.addLayout(head)

        bar = QtWidgets.QHBoxLayout()
        b_refresh = QtWidgets.QPushButton("刷新")
        b_refresh.clicked.connect(self.reload)
        b_all = QtWidgets.QPushButton("全选")
        b_all.clicked.connect(lambda: self._set_all(True))
        b_none = QtWidgets.QPushButton("全不选")
        b_none.clicked.connect(lambda: self._set_all(False))
        b_new = QtWidgets.QPushButton("选新增（自上次归档）")
        b_new.clicked.connect(self._select_new)
        for b in (b_refresh, b_all, b_none, b_new):
            bar.addWidget(b)
        bar.addStretch(1)
        self.count_label = QtWidgets.QLabel("")
        self.count_label.setObjectName("muted")
        bar.addWidget(self.count_label)
        lay.addLayout(bar)

        self.list = QtWidgets.QListWidget()
        self.list.setViewMode(QtWidgets.QListView.IconMode)
        self.list.setIconSize(QtCore.QSize(96, 96))
        self.list.setGridSize(QtCore.QSize(130, 140))
        self.list.setResizeMode(QtWidgets.QListView.Adjust)
        self.list.setWordWrap(True)
        self.list.itemChanged.connect(lambda _item: self._update_count())
        lay.addWidget(self.list, 1)

        row = QtWidgets.QHBoxLayout()
        hint = QtWidgets.QLabel("只增不删：同名同大小跳过；同名不同大小改名续位；按日期分夹落库。")
        hint.setObjectName("muted")
        row.addWidget(hint)
        row.addStretch(1)
        self.go_btn = QtWidgets.QPushButton("📥 归档选中 (0)")
        self.go_btn.setObjectName("primary")
        self.go_btn.clicked.connect(self._archive_selected)
        row.addWidget(self.go_btn)
        lay.addLayout(row)

    # ---------- 当前区 ----------

    def _kind(self) -> tuple:
        idx = self.kind_combo.currentIndex()
        return _KINDS[max(0, idx)]

    def _target(self) -> str:
        _, _k, _exts, target_key, _w = self._kind()
        default = DEFAULT_ARCHIVE_TARGET if target_key == "archive_target" \
            else DEFAULT_VIDEO_TARGET
        return self.store.load().get_ui_pref(target_key, default)

    def _watermark(self) -> float:
        _, _k, _exts, _t, wm_key = self._kind()
        try:
            return float(self.store.load().get_ui_pref(wm_key, "0"))
        except (ValueError, TypeError):
            logging.getLogger(__name__).debug("归档水位非数值，按 0 处理")
            return 0.0

    # ---------- 数据 ----------

    def reload(self) -> None:
        label, _k, _exts, _t, _w = self._kind()
        self.target_label.setText(f"{label}落点：{self._target()}")
        self._stop_thumbs()
        self.list.clear()
        self._items = []

        def job():
            ctx = build_context(self.store.load())
            _label, _kind, exts, _t, _w = self._kind()
            return {"ok": True,
                    "items": list_recent_outputs(output_dir_of(ctx.comfyui_root),
                                                 exts=exts)}
        self.status_cb(f"扫描 {label}输出…")
        self._run(job, self._on_loaded)

    def _on_loaded(self, ok: bool, payload: dict) -> None:
        if not ok:
            self.status_cb(f"扫描失败: {payload.get('error')}")
            return
        self._items = payload["items"]
        wm = self._watermark()
        for it in self._items:
            mtime = datetime.fromtimestamp(it["mtime"]).strftime("%m-%d %H:%M")
            fname = Path(it["rel"]).name
            if len(fname) > 20:
                fname = fname[:19] + "…"
            text = f"{fname}\n{_fmt_size(it['size'])} · {mtime}"
            item = QtWidgets.QListWidgetItem(text)
            item.setData(QtCore.Qt.UserRole, it)
            item.setFlags(QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsEnabled
                          | QtCore.Qt.ItemIsSelectable)
            item.setCheckState(QtCore.Qt.Checked if it["mtime"] > wm
                               else QtCore.Qt.Unchecked)
            item.setToolTip(f"{it['rel']}\n{_fmt_size(it['size'])} · {mtime}")
            self.list.addItem(item)
        self._update_count()
        n_new = sum(1 for i in self._items if i["mtime"] > wm)
        self.status_cb(f"{len(self._items)} 个（新增 {n_new}）")
        # 图像区：后台补缩略图
        _label, kind, _exts, _t, _w = self._kind()
        if kind == "image" and self._items:
            self._thumb_worker = ThumbWorker(self._items, parent=self)
            self._thumb_worker.thumb_sig.connect(self._apply_thumb)
            self._thumb_worker.start()

    def _apply_thumb(self, index: int, qimage) -> None:
        if index >= self.list.count():
            return
        item = self.list.item(index)
        if item is None:
            return
        if not qimage.isNull():
            from PyQt5.QtGui import QIcon, QPixmap
            item.setIcon(QIcon(QPixmap.fromImage(qimage)))
        self.list.doItemsLayout()

    def _stop_thumbs(self) -> None:
        if self._thumb_worker is not None:
            self._thumb_worker.stop()
            self._thumb_worker.wait(2000)
            self._thumb_worker = None

    # ---------- 选择 ----------

    def _checked_items(self) -> list[dict]:
        out = []
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.checkState() == QtCore.Qt.Checked:
                out.append(item.data(QtCore.Qt.UserRole))
        return out

    def _set_all(self, checked: bool) -> None:
        self._bulk = True
        state = QtCore.Qt.Checked if checked else QtCore.Qt.Unchecked
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(state)
        self._bulk = False
        self._update_count()

    def _select_new(self) -> None:
        wm = self._watermark()
        self._bulk = True
        for i in range(self.list.count()):
            it = self.list.item(i).data(QtCore.Qt.UserRole)
            self.list.item(i).setCheckState(
                QtCore.Qt.Checked if it["mtime"] > wm else QtCore.Qt.Unchecked)
        self._bulk = False
        self._update_count()

    def _update_count(self) -> None:
        if self._bulk:
            return
        n = len(self._checked_items())
        self.go_btn.setText(f"📥 归档选中 ({n})")

    # ---------- 动作 ----------

    def _archive_selected(self) -> None:
        files = self._checked_items()
        if not files:
            QtWidgets.QMessageBox.information(self, "未选择", "先勾选要归档的文件")
            return
        label, _k, _e, _t, wm_key = self._kind()
        target = self._target()

        def job():
            return {"ok": True, **archive_files(files, target)}
        self.go_btn.setEnabled(False)
        self.status_cb(f"归档 {len(files)} 个{label} → {target}…")
        self._run(job, self._on_archived)

    def _on_archived(self, ok: bool, payload: dict) -> None:
        self.go_btn.setEnabled(True)
        copied = payload.get("copied", [])
        skipped = payload.get("skipped", [])
        renamed = payload.get("renamed", [])
        failed = payload.get("failed", [])
        if copied:
            _label, _k, _e, _t, wm_key = self._kind()
            cfg = self.store.load()
            cfg.set_ui_pref(wm_key, str(datetime.now().timestamp()))
            self.store.save(cfg)
        summary = (f"新增 {len(copied)}　已存在跳过 {len(skipped)}"
                   f"　改名 {len(renamed)}　失败 {len(failed)}\n\n落点：{payload.get('target')}")
        if failed:
            QtWidgets.QMessageBox.warning(
                self, "归档完成（有失败）",
                summary + "\n\n失败明细：\n"
                + "\n".join(f"{f['rel']}: {f['reason']}" for f in failed[:8])
                + ("…" if len(failed) > 8 else ""))
        else:
            QtWidgets.QMessageBox.information(self, "归档完成", summary)
        self.status_cb(f"归档完成：新增 {len(copied)}，跳过 {len(skipped)}，失败 {len(failed)}")
        self.reload()

    # ---------- 基础 ----------

    def _run(self, fn, on_done):
        self._worker = FunctionWorker(fn, self)
        self._worker.finished_sig.connect(on_done)
        self._worker.start()

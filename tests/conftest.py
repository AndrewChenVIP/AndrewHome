from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="session")
def qapp():
    """共享一个 offscreen QApplication（未装 pytest-qt，自建）。"""
    from PyQt5 import QtWidgets
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


@pytest.fixture()
def home(tmp_path) -> Path:
    """独立配置目录：每个测试自成一个世界。"""
    d = tmp_path / "launchpad-home"
    d.mkdir()
    return d


@pytest.fixture()
def fake_env_home(home, tmp_path) -> Path:
    """预置一个指向假 ComfyUI 布局的环境。"""
    root = tmp_path / "fakepkg"
    (root / "ComfyUI" / "user").mkdir(parents=True)
    (root / "ComfyUI" / "main.py").write_text("print('fake')\n", encoding="utf-8")
    import json

    cfg = {
        "schema_version": 1,
        "active_env_id": "fake",
        "environments": [{
            "id": "fake", "name": "假环境", "comfyui_root": str(root),
            "python_path": sys.executable, "main_script": "",
        }],
        "launch": {"port": 18188, "windows_standalone": False, "auto_open_browser": False},
        "mirrors": {},
    }
    (home / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return home

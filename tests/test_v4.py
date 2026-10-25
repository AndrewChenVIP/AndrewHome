"""v0.4 测试：UI 偏好持久化 / info --env / GUI 主题与环境下拉。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from wandao_launchpad.cli import main as cli_main
from wandao_launchpad.cli import exitcodes as ec
from wandao_launchpad.config import Config, ConfigStore, Environment


def test_ui_pref_roundtrip(home):
    store = ConfigStore(home)
    cfg = Config()
    cfg.environments.append(Environment(id="a", name="A"))
    assert cfg.get_ui_pref("theme", "light") == "light"   # 缺省
    cfg.set_ui_pref("theme", "dark")
    store.save(cfg)

    loaded = store.load()
    assert loaded.get_ui_pref("theme") == "dark"
    # 落盘检查：extras 原样保留（前向兼容袋不丢）
    raw = json.loads((home / "config.json").read_text(encoding="utf-8-sig"))
    assert raw["ui"]["theme"] == "dark"


def _home_two_envs(home) -> Path:
    cfg = Config()
    cfg.environments = [
        Environment(id="e1", name="一号", comfyui_root="R1", python_path="P1"),
        Environment(id="e2", name="二号", comfyui_root="R2", python_path="P2"),
    ]
    cfg.active_env_id = "e1"
    ConfigStore(home).save(cfg)
    return home


def test_info_env_resolution(home, capsys):
    home = _home_two_envs(home)
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli_main(["--home", str(home), "--json", "info"])
    payload = json.loads([l for l in buf.getvalue().splitlines() if l.strip()][-1])
    assert code == ec.EXIT_OK
    assert payload["comfyui_root"] == "R1"
    assert payload["resolved_from"] == "active"

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli_main(["--home", str(home), "--json", "info", "--env", "e2"])
    payload = json.loads([l for l in buf.getvalue().splitlines() if l.strip()][-1])
    assert code == ec.EXIT_OK
    assert payload["comfyui_root"] == "R2" and payload["python_path"] == "P2"
    assert payload["resolved_from"] == "--env=e2"

    # 未知 env：报错退 1（不再静默回 active）
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = cli_main(["--home", str(home), "--json", "info", "--env", "ghost"])
    assert code == ec.EXIT_ERROR


def test_gui_theme_switch_and_env_combo(home, qapp):
    from wandao_launchpad.gui import theme
    from wandao_launchpad.gui.main_window import MainWindow

    _home_two_envs(home)
    store = ConfigStore(home)
    win = MainWindow(store)
    try:
        win._refresh_env_label()   # 平时由启动 QTimer 触发，测试无事件循环，手动刷
        # 主题切换：实时换 QSS + 持久化
        win._apply_theme("dark")
        assert theme.current_theme() == "dark"
        assert "#14161c" in qapp.styleSheet()      # 深色 window_bg token 已生效
        assert store.load().get_ui_pref("theme") == "dark"
        # 环境下拉：切到二号 → 配置落盘
        idx = win.env_combo.findData("e2")
        assert idx >= 0
        win.env_combo.setCurrentIndex(idx)
        assert store.load().active_env_id == "e2"
        assert win.env_combo.count() == 2
    finally:
        win.close()

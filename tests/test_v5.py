"""v0.5 测试：支持包 zip / 托盘偏好 / 快捷目录解析。"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

from wandao_launchpad.config import Config, ConfigStore, Environment
from wandao_launchpad.constants import pidfile_path
from wandao_launchpad.context import build_context
from wandao_launchpad.support import build_support_zip


def _ctx_with_fake_pkg(tmp_path: Path):
    root = tmp_path / "pkg"
    (root / "ComfyUI" / "custom_nodes" / "nodeX").mkdir(parents=True)
    (root / "ComfyUI" / "user").mkdir()
    log = root / "ComfyUI" / "user" / "comfyui.log"
    log.write_text("\n".join(f"line{i}" for i in range(1, 1201)) + "\n", encoding="utf-8")
    cfg = Config()
    cfg.environments = [Environment(id="e", name="E", comfyui_root=str(root),
                                    python_path=sys.executable)]
    cfg.active_env_id = "e"
    cfg.launch.port = 18999   # 避开真机 8188（测试与真环境互不干扰）
    return cfg, log


def test_support_zip_contents(tmp_path, home):
    cfg, log = _ctx_with_fake_pkg(tmp_path)
    store = ConfigStore(home)
    store.save(cfg)
    ctx = build_context(store.load())

    out = tmp_path / "sup.zip"
    path = build_support_zip(ctx, pidfile_path(home), out)

    with zipfile.ZipFile(path) as zf:
        names = set(zf.namelist())
        assert "info.json" in names
        assert "comfyui-tail.log" in names
        info = json.loads(zf.read("info.json").decode("utf-8"))
        assert info["launcher_version"] and info["environment"]["id"] == "e"
        assert info["status"]["running"] is False
        assert {p["name"] for p in info["plugins"]} == {"nodeX"}
        # 尾部日志：只带最后 500 行（1200-500+1=701 起），不带前段
        tail = zf.read("comfyui-tail.log").decode("utf-8")
        assert "line1200" in tail and "line701" in tail
        assert "line700" not in tail and "line1\n" not in tail


def test_support_cli(home, tmp_path, capsys):
    cfg, _ = _ctx_with_fake_pkg(tmp_path)
    ConfigStore(home).save(cfg)
    from wandao_launchpad.cli import main as cli_main
    from wandao_launchpad.cli import exitcodes as ec
    import contextlib
    import io
    buf = io.StringIO()
    out_zip = tmp_path / "via-cli.zip"
    with contextlib.redirect_stdout(buf):
        code = cli_main(["--home", str(home), "--json", "support", "--out", str(out_zip)])
    assert code == ec.EXIT_OK
    payload = json.loads([l for l in buf.getvalue().splitlines() if l.strip()][-1])
    assert payload["ok"] is True and out_zip.exists()


def test_tray_pref_and_close_to_tray(home, qapp, tmp_path):
    cfg, _ = _ctx_with_fake_pkg(tmp_path)
    store = ConfigStore(home)
    store.save(cfg)
    # 偏好关闭（默认）：closeEvent 走真关闭路径（offscreen 无系统托盘 → _tray=None，
    # 即便偏好开也退回真关闭——托盘不可用时藏窗=失联，必须拒绝）
    from wandao_launchpad.gui.main_window import MainWindow
    win = MainWindow(store)
    assert win._tray is None  # offscreen 环境无托盘
    from PyQt5 import QtGui
    ev = QtGui.QCloseEvent()
    win.store.load().set_ui_pref("close_to_tray", "1")
    win.store.save(win.store.load())
    win.closeEvent(ev)
    assert ev.isAccepted() is True   # 无托盘可用 → 不藏窗，直接关（防失联）
    win.close()


def test_quick_paths(home, tmp_path):
    cfg, _ = _ctx_with_fake_pkg(tmp_path)
    store = ConfigStore(home)
    store.save(cfg)
    from wandao_launchpad.gui.main_window import MainWindow
    win = MainWindow(store)
    paths = win._quick_paths()
    assert paths["output"].name == "output"
    assert paths["nodes"].name == "custom_nodes"
    assert paths["log"].name == "comfyui.log"
    win.close()

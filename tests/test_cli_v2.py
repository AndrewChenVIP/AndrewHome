"""v0.2 新子命令（plugins/kernel/models）的 CLI 契约测试。"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_services import _git, _commit, _make_repo_with_remote
from wandao_launchpad.cli import main as cli_main
from wandao_launchpad.cli import exitcodes as ec


def _home_with_pkg(tmp_path: Path) -> Path:
    home = tmp_path / "home2"
    home.mkdir()
    root = tmp_path / "pkg2"
    (root / "ComfyUI" / "custom_nodes").mkdir(parents=True)
    (root / "ComfyUI" / "custom_nodes" / "nodeX").mkdir()
    (root / "ComfyUI" / "custom_nodes" / "nodeY.disabled").mkdir()
    _make_kernel(root / "ComfyUI", tmp_path)
    cfg = {
        "schema_version": 1,
        "active_env_id": "e",
        "environments": [{"id": "e", "name": "e", "comfyui_root": str(root),
                          "python_path": sys.executable}],
        "launch": {"port": 18288, "windows_standalone": False,
                   "auto_open_browser": False},
        "mirrors": {},
    }
    (home / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return home


def _make_kernel(repo: Path, tmp: Path) -> None:
    _git(repo, "init", "-b", "main")
    (repo / "comfyui_version.py").write_text('__version__ = "9.9.9"', encoding="utf-8")
    _commit(repo, "init kernel")


def _run(home: Path, *argv):
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = cli_main(["--home", str(home), "--json", *argv])
    lines = [ln for ln in buf.getvalue().strip().splitlines() if ln.strip()]
    return code, (json.loads(lines[-1]) if lines else {})


def test_plugins_list_contract(tmp_path):
    home = _home_with_pkg(tmp_path)
    code, payload = _run(home, "plugins", "list")
    assert code == ec.EXIT_OK
    names = {p["name"] for p in payload["plugins"]}
    assert names == {"nodeX", "nodeY"}
    assert payload["count"] == 2


def test_plugins_enable_disable(tmp_path):
    home = _home_with_pkg(tmp_path)
    code, payload = _run(home, "plugins", "disable", "nodeX")
    assert code == ec.EXIT_OK and payload["plugin"]["enabled"] is False
    code, payload = _run(home, "plugins", "list")
    assert "nodeX.disabled" in {p["dir_name"] for p in payload["plugins"]}
    _run(home, "plugins", "enable", "nodeX.disabled")


def test_plugins_uninstall_needs_yes(tmp_path):
    home = _home_with_pkg(tmp_path)
    code, payload = _run(home, "plugins", "uninstall", "nodeX")
    assert code == ec.EXIT_ERROR and "--yes" in payload["error"]
    code, payload = _run(home, "plugins", "uninstall", "nodeX", "--yes")
    assert code == ec.EXIT_OK


def test_kernel_info_contract(tmp_path):
    home = _home_with_pkg(tmp_path)
    code, payload = _run(home, "kernel", "info")
    assert code == ec.EXIT_OK
    assert payload["comfyui_version"] == "9.9.9"
    assert payload["commit"]


def test_kernel_log_and_update_latest(tmp_path):
    home = _home_with_pkg(tmp_path)
    code, payload = _run(home, "kernel", "log", "-n", "5")
    assert code == ec.EXIT_OK and payload["count"] == 1
    # 无远端 → update 报错（fetch 失败），退出 1；给远端后 already-latest → 4
    code, payload = _run(home, "kernel", "update")
    assert code == ec.EXIT_ERROR and "fetch" in payload["error"]


def test_models_lifecycle(tmp_path):
    home = _home_with_pkg(tmp_path)
    root = json.loads((home / "config.json").read_text(encoding="utf-8-sig")) \
        ["environments"][0]["comfyui_root"]
    libroot = tmp_path / "m"
    (libroot / "checkpoints").mkdir(parents=True)
    # 手写一份历史 yaml → import → list → apply
    (Path(root) / "ComfyUI" / "extra_model_paths.yaml").write_text(
        "old:\n  base_path: " + str(libroot).replace("\\", "/") + "\n  checkpoints: checkpoints/\n",
        encoding="utf-8")
    code, payload = _run(home, "models", "import")
    assert code == ec.EXIT_OK and payload["imported"] == 1
    code, payload = _run(home, "models", "list")
    assert code == ec.EXIT_OK and payload["count"] == 1
    assert payload["libraries"][0]["effective_mappings"] == {"checkpoints": "checkpoints"}
    code, payload = _run(home, "models", "apply")
    assert code == ec.EXIT_OK and payload["applied"] is True
    code, payload = _run(home, "models", "validate")
    assert code == ec.EXIT_OK and payload["problems"] == []

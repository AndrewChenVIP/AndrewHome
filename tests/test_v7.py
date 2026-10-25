"""v0.7 测试：pipx 冻结过滤 / 依赖联动 / doctor 体检。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from wandao_launchpad.config import Config, ConfigStore, Environment
from wandao_launchpad.context import build_context
from wandao_launchpad.doctor import blockers, run_checks, summarize
from wandao_launchpad.pipx import (FROZEN_PKGS, build_install_cmd,
                                   ensure_requirements, filter_requirements,
                                   is_frozen_line)


# ---------- pipx 纯函数 ----------

def test_frozen_filter():
    text = "torch>=2.3\ntorchaudio\n# comment\ncomfyui-frontend-package==1.2.3\n" \
           "safety\nTorchVision\n-git+https://x\n\nnumpy"
    filtered, dropped = filter_requirements(text)
    assert "torch" not in filtered
    assert "comfyui-frontend-package==1.2.3" in filtered
    assert "numpy" in filtered
    assert len(dropped) == 3  # torch / torchaudio / TorchVision（大小写归一）
    assert not is_frozen_line("# torch")
    assert not is_frozen_line("")
    assert not is_frozen_line("--index-url https://x")
    # Torch_Vision 归一为 torch-vision ≠ torchvision：不是冻结包（PEP 503 语义）
    assert not is_frozen_line("Torch_Vision")


def test_build_install_cmd():
    argv = build_install_cmd("PY", Path("r.txt"), "https://mirror/simple", upgrade=True)
    assert argv[:4] == ["PY", "-m", "pip", "install"]
    assert "-r" in argv
    assert "--upgrade" in argv and "only-if-needed" in argv
    assert argv[-1] == "https://mirror/simple"
    plain = build_install_cmd("PY", Path("r.txt"), None, upgrade=False)
    assert "--upgrade" not in plain and "-i" not in plain


def test_ensure_requirements_missing_file(tmp_path):
    r = ensure_requirements(tmp_path, sys.executable)
    assert r["ran"] is False and r["ok"] is None


def test_ensure_requirements_real_pip_help(tmp_path):
    """真 pip 路径：requirements 指向 --help 这类无害参数不适用（-r 会真装），
    改用空 requirements 文件——pip 对空文件成功返回，装了 0 个包。"""
    (tmp_path / "requirements.txt").write_text("# nothing\n", encoding="utf-8")
    r = ensure_requirements(tmp_path, sys.executable)
    assert r["ran"] is True and r["ok"] is True


# ---------- doctor ----------

def _ctx(tmp_path, **env_kw):
    root = tmp_path / "pkg"
    (root / "ComfyUI" / "user").mkdir(parents=True)
    (root / "ComfyUI" / "main.py").write_text("", encoding="utf-8")
    cfg = Config()
    cfg.environments = [Environment(id="e", name="E", comfyui_root=str(root),
                                    python_path=sys.executable)]
    cfg.active_env_id = "e"
    cfg.launch.port = 18999  # 避让真机
    return build_context(cfg)


def test_doctor_all_ok_path(tmp_path):
    checks = run_checks(_ctx(tmp_path), quick=True)
    fails = blockers(checks)
    assert fails == []
    levels = {c["name"]: c["level"] for c in checks}
    assert levels["Python"] == "ok"
    assert levels["ComfyUI 入口"] == "ok"
    assert levels["端口"] == "ok"      # 18999 无服务
    nf, nw = summarize(checks)
    assert nf == 0


def test_doctor_full_mode_includes_pip_and_kernel(tmp_path):
    checks = run_checks(_ctx(tmp_path), quick=False)
    names = {c["name"] for c in checks}
    assert "pip" in names
    assert "内核仓库" in names   # 无 .git → warn
    assert blockers(checks) == []


def test_doctor_missing_python_is_fail(tmp_path):
    ctx = _ctx(tmp_path)
    from wandao_launchpad.config import Config as C
    cfg = C(active_env_id="e",
            environments=[Environment(id="e", name="E",
                                      comfyui_root=ctx.comfyui_root,
                                      python_path="Q:/no/python.exe")])
    checks = run_checks(build_context(cfg), quick=True)
    fails = blockers(checks)
    assert any(f["name"] == "Python" for f in fails)


def test_doctor_missing_main_is_fail(tmp_path):
    root = tmp_path / "pkg2"
    (root / "ComfyUI").mkdir(parents=True)
    cfg = Config(active_env_id="e",
                 environments=[Environment(id="e", name="E", comfyui_root=str(root),
                                           python_path=sys.executable)])
    checks = run_checks(build_context(cfg), quick=True)
    assert any(f["name"] == "ComfyUI 入口" for f in blockers(checks))


# ---------- CLI doctor 契约 ----------

def test_cli_doctor_contract(tmp_path, home):
    root = tmp_path / "pkg3"
    (root / "ComfyUI" / "user").mkdir(parents=True)
    (root / "ComfyUI" / "main.py").write_text("", encoding="utf-8")
    cfg = {"schema_version": 1, "active_env_id": "e",
           "environments": [{"id": "e", "name": "E", "comfyui_root": str(root),
                             "python_path": sys.executable}],
           "launch": {"port": 18999, "windows_standalone": False,
                      "auto_open_browser": False},
           "mirrors": {}}
    (home / "config.json").write_text(json.dumps(cfg), encoding="utf-8")

    import contextlib
    import io
    from wandao_launchpad.cli import main as cli_main
    from wandao_launchpad.cli import exitcodes as ec

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli_main(["--home", str(home), "--json", "doctor"])
    payload = json.loads([l for l in buf.getvalue().splitlines() if l.strip()][-1])
    assert code == ec.EXIT_OK
    assert payload["ok"] is True and payload["fail"] == 0
    assert any(c["name"] == "pip" for c in payload["checks"])

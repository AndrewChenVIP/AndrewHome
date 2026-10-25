"""生命周期 e2e——用假 ComfyUI（scripts/fake_comfyui.py）走完整的
start → status → start(拒绝) → stop → status 链，验契约也验真实进程行为。
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from wandao_launchpad.cli import main as cli_main
from wandao_launchpad.cli import exitcodes as ec
from wandao_launchpad.constants import pidfile_path

FAKE_SRC = Path(__file__).resolve().parent.parent / "scripts" / "fake_comfyui.py"
PORT = 18198


@pytest.fixture()
def fake_home(tmp_path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    root = tmp_path / "pkg"
    (root / "ComfyUI" / "user").mkdir(parents=True)
    shutil.copy(FAKE_SRC, root / "ComfyUI" / "fake_comfyui.py")
    log = tmp_path / "fake.log"
    cfg = {
        "schema_version": 1,
        "active_env_id": "fake",
        "environments": [{
            "id": "fake", "name": "假包", "comfyui_root": str(root),
            "python_path": sys.executable,
            "main_script": "ComfyUI/fake_comfyui.py",
        }],
        "launch": {
            "port": PORT, "windows_standalone": False, "auto_open_browser": False,
            "extra_args": f"--port {PORT} --log-file {str(log)}",
        },
        "mirrors": {},
    }
    (home / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    yield home
    # 兜底清扫：即使断言失败也别留孤儿进程
    _force_stop(home)


def _force_stop(home: Path) -> None:
    try:
        cli_main(["--home", str(home), "--json", "stop"])
    except Exception:
        pass


def _run(home: Path, *argv):
    import io
    import contextlib
    buf_out, buf_err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
        code = cli_main(["--home", str(home), "--json", *argv])
    out = buf_out.getvalue()
    lines = [ln for ln in out.strip().splitlines() if ln.strip()]
    return code, (json.loads(lines[-1]) if lines else {})


def test_full_lifecycle(fake_home, tmp_path):
    # 1) 起步：未运行
    code, payload = _run(fake_home, "status")
    assert code == ec.EXIT_NOT_RUNNING and payload["running"] is False

    # 2) 启动并等待就绪（阻塞式）
    code, payload = _run(fake_home, "start", "--timeout", "30")
    assert code == ec.EXIT_OK, f"start 失败: {payload}"
    assert payload["started"] is True and payload["ready"] is True
    pid = payload["pid"]
    assert pid and pid > 0

    # 3) 重复启动：拒绝 + 退出码 2 + 带回占用者
    code, payload = _run(fake_home, "start")
    assert code == ec.EXIT_ALREADY_RUNNING
    assert payload["started"] is False
    assert payload["running_env_id"] == "fake"

    # 4) 运行中 status
    code, payload = _run(fake_home, "status")
    assert code == ec.EXIT_OK
    assert payload["running"] is True and payload["pid"] == pid

    # 5) pidfile 记录了身份字段（防 PID 复用）
    rec = json.loads(pidfile_path(fake_home).read_text(encoding="utf-8-sig"))
    assert rec["proc_create_time"] > 0 and rec["env_id"] == "fake"

    # 6) 停止：真的停了
    code, payload = _run(fake_home, "stop")
    assert code == ec.EXIT_OK
    assert payload["stopped"] is True and payload["pid"] == pid

    # 7) 停后：未运行 + pidfile 清理
    code, payload = _run(fake_home, "status")
    assert code == ec.EXIT_NOT_RUNNING
    assert not pidfile_path(fake_home).exists()

    # 8) 再停一次：幂等成功
    code, payload = _run(fake_home, "stop")
    assert code == ec.EXIT_OK and payload["stopped"] is False


def test_restart_from_dead(fake_home):
    code, payload = _run(fake_home, "restart", "--timeout", "30")
    assert code == ec.EXIT_OK and payload["ready"] is True
    _force_stop(fake_home)


def test_logs_tail(fake_home, tmp_path):
    # 日志落点 = 上下文解析的位置（root/ComfyUI/user/comfyui.log）
    root = tmp_path / "pkg"
    log = root / "ComfyUI" / "user" / "comfyui.log"
    log.write_text("line1\nline2\nline3\n", encoding="utf-8")
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli_main(["--home", str(fake_home), "--json", "logs", "comfyui", "-n", "2"])
    assert code == ec.EXIT_OK
    tail = buf.getvalue().strip().splitlines()
    assert tail == ["line2", "line3"]  # 真_tail 只取最后 N 行

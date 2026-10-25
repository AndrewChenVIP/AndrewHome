from __future__ import annotations

import io
import json
import sys

import pytest

from wandao_launchpad.cli import main as cli_main
from wandao_launchpad.cli import exitcodes as ec


def run_cli(capsys, *argv) -> tuple[int, str, str]:
    code = cli_main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def _last_json(stdout: str) -> dict:
    lines = [ln for ln in stdout.strip().splitlines() if ln.strip()]
    return json.loads(lines[-1])


# ---------- info ----------

def test_info_json_contract(home, capsys):
    code, out, _ = run_cli(capsys, "--home", str(home), "--json", "info")
    assert code == ec.EXIT_OK
    payload = _last_json(out)
    for key in ("launcher_version", "active_env_id", "environments", "port",
                "launch", "mirrors", "config_path"):
        assert key in payload, f"契约字段缺失: {key}"


# ---------- 未配置环境的行为 ----------

def test_start_without_env_errors(home, capsys):
    code, out, _ = run_cli(capsys, "--home", str(home), "--json", "start")
    assert code == ec.EXIT_ERROR
    assert "环境" in _last_json(out)["error"]


def test_status_without_env_errors(home, capsys):
    code, _, _ = run_cli(capsys, "--home", str(home), "--json", "status")
    assert code == ec.EXIT_ERROR


def test_status_not_running_exit3(fake_env_home, capsys):
    code, out, _ = run_cli(capsys, "--home", str(fake_env_home), "--json", "status")
    assert code == ec.EXIT_NOT_RUNNING
    payload = _last_json(out)
    assert payload["running"] is False
    assert payload["pid"] is None


def test_stop_idempotent_when_not_running(fake_env_home, capsys):
    code, out, _ = run_cli(capsys, "--home", str(fake_env_home), "--json", "stop")
    assert code == ec.EXIT_OK
    assert _last_json(out)["stopped"] is False


def test_env_flag_with_unknown_id(fake_env_home, capsys):
    code, out, _ = run_cli(capsys, "--home", str(fake_env_home), "--json",
                           "info", "--env", "ghost")
    # info 不接受无效 env 也应报错而非崩
    assert code in (ec.EXIT_OK, ec.EXIT_ERROR)


def test_logs_missing_file_exit1(fake_env_home, capsys):
    code, out, _ = run_cli(capsys, "--home", str(fake_env_home), "--json",
                           "logs", "comfyui", "-n", "5")
    assert code == ec.EXIT_ERROR

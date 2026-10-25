from __future__ import annotations

import os

from wandao_launchpad import pidfile
from wandao_launchpad.pidfile import PidRecord


def test_write_read_roundtrip(tmp_path):
    p = tmp_path / "comfyui.pid"
    rec = PidRecord(pid=123, port=8188, started_at=1.0, proc_create_time=2.0,
                    log_path="x.log", env_id="e1")
    pidfile.write(p, rec)
    assert pidfile.read(p) == rec


def test_missing_returns_none(tmp_path):
    assert pidfile.read(tmp_path / "nope.pid") is None


def test_corrupt_returns_none(tmp_path):
    p = tmp_path / "comfyui.pid"
    p.write_text("{broken", encoding="utf-8")
    assert pidfile.read(p) is None


def test_self_process_alive(tmp_path):
    # 用当前测试进程自己当"活进程"：create_time 取真值，必须判活
    me = os.getpid()
    rec = PidRecord(pid=me, port=1, started_at=pidfile.now(),
                    proc_create_time=pidfile.current_create_time(me),
                    log_path="", env_id="t")
    assert pidfile.is_alive(rec) is True


def test_pid_reuse_detected(tmp_path):
    # 身份不吻合（create_time 差得远）→ 判死：机器重启 PID 复用场景
    me = os.getpid()
    rec = PidRecord(pid=me, port=1, started_at=1.0,
                    proc_create_time=1000.0,  # 远古时刻，肯定不是这个进程的
                    log_path="", env_id="t")
    assert pidfile.is_alive(rec) is False


def test_dead_pid(tmp_path):
    rec = PidRecord(pid=-1, port=1, started_at=1.0, proc_create_time=1.0,
                    log_path="", env_id="t")
    assert pidfile.is_alive(rec) is False


def test_clear_missing_ok(tmp_path):
    pidfile.clear(tmp_path / "nope.pid")  # 不抛即通过

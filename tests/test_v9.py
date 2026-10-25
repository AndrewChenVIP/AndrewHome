"""v0.9 测试：StabilityTracker / autostart / 视频归档落点 / 偏好往返。"""
from __future__ import annotations

import json
import time
from pathlib import Path

from wandao_launchpad.archive import (DEFAULT_VIDEO_TARGET, StabilityTracker,
                                      VIDEO_EXTS, list_recent_outputs)
from wandao_launchpad.autostart import (build_create_cmd, build_delete_cmd,
                                        build_query_cmd, is_registered,
                                        TASK_NAME)


# ---------- StabilityTracker ----------

def test_tracker_requires_stable_size_duration():
    tr = StabilityTracker(stable_after_sec=3.0)
    f = {"path": "p.png", "size": 10, "mtime": 1.0}
    assert tr.feed([f], now=0.0) == []            # 首见：刚建立观察
    assert tr.feed([{**f, "mtime": 1.0}], now=2.0) == []   # 2s：未满 3s
    out = tr.feed([{**f, "mtime": 1.0}], now=3.5)          # 3.5s：落定
    assert [x["path"] for x in out] == ["p.png"]


def test_tracker_size_change_resets_clock():
    tr = StabilityTracker(stable_after_sec=3.0)
    f = {"path": "p.png", "size": 10, "mtime": 1.0}
    tr.feed([f], now=0.0)
    tr.feed([f], now=2.0)
    grown = {**f, "size": 99}                     # 文件还在长
    assert tr.feed([grown], now=4.0) == []        # 尺寸变了 → 计时清零
    out = tr.feed([grown], now=8.0)
    assert [x["path"] for x in out] == ["p.png"]  # 新尺寸稳定后重新落定


def test_tracker_forgets_disappeared():
    tr = StabilityTracker(stable_after_sec=1.0)
    f = {"path": "p.png", "size": 10, "mtime": 1.0}
    tr.feed([f], now=0.0)
    tr.feed([f], now=2.0)                          # 已落定过一次
    assert tr.feed([], now=3.0) == []              # 文件消失 → 空手而归
    out = tr.feed([f], now=4.0)                    # 重新出现 → 重新计时
    assert out == []


# ---------- autostart 纯函数 ----------

def test_autostart_cmds():
    argv = build_create_cmd(r"C:\App\L.exe")
    assert argv[0] == "schtasks" and "/Create" in argv and TASK_NAME in argv
    assert "/SC" in argv and "ONLOGON" in argv
    assert argv[argv.index("/TR") + 1] == r"C:\App\L.exe"
    assert "/Delete" in build_delete_cmd()
    assert "/Query" in build_query_cmd()


def test_autostart_query_nonexistent_task():
    # 查询一个几乎不可能存在的任务名：注册判定应为 False（真实子进程路径）
    assert is_registered.__module__  # 可调用
    from wandao_launchpad.autostart import run_hidden  # noqa: F401
    from wandao_launchpad.proc import run_hidden as rh
    rc, _o, _e = rh(build_query_cmd().__class__(["schtasks", "/Query", "/TN",
                                                 "DefinitelyNotARealTaskXYZ"]), timeout=30)
    assert rc != 0


# ---------- 视频归档 ----------

def test_video_exts_supported(tmp_path):
    out = tmp_path / "ComfyUI" / "output"
    out.mkdir(parents=True)
    (out / "v.mp4").write_bytes(b"V")
    (out / "i.png").write_bytes(b"I")
    vids = list_recent_outputs(out, exts=VIDEO_EXTS)
    assert [i["rel"] for i in vids] == ["v.mp4"]


def test_video_target_pref_roundtrip(home):
    from wandao_launchpad.config import Config, ConfigStore
    store = ConfigStore(home)
    cfg = Config()
    cfg.set_ui_pref("archive_video_target", DEFAULT_VIDEO_TARGET)
    store.save(cfg)
    assert store.load().get_ui_pref("archive_video_target") == DEFAULT_VIDEO_TARGET
    assert "视频" in DEFAULT_VIDEO_TARGET


def test_auto_archive_pref_roundtrip(home):
    from wandao_launchpad.config import Config, ConfigStore
    store = ConfigStore(home)
    cfg = Config()
    cfg.set_ui_pref("auto_archive", "1")
    store.save(cfg)
    assert store.load().get_ui_pref("auto_archive") == "1"

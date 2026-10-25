"""v0.8 测试：出图归档（只增不删语义）+ CLI 契约。"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from wandao_launchpad.archive import (archive_files, list_recent_outputs,
                                      output_dir_of)
from wandao_launchpad.cli import exitcodes as ec
from wandao_launchpad.cli import main as cli_main


def _make_output(tmp_path: Path, files: dict[str, tuple[bytes, float]]) -> Path:
    """files: rel -> (content, mtime_offset_sec)"""
    root = tmp_path / "pkg"
    out = root / "ComfyUI" / "output"
    for rel, (content, dt) in files.items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content)
        stamp = time.time() - dt
        os.utime(p, (stamp, stamp))
    return root


def test_list_recent_outputs_sort_and_filter(tmp_path):
    root = _make_output(tmp_path, {
        "a.png": (b"A" * 10, 100),            # 最新（100 秒前）
        "sub/b.png": (b"B" * 10, 200),
        "c.jpg": (b"C" * 10, 300),            # 最旧
        "video.mp4": (b"V" * 10, 400),        # 非图像，排除
        "note.txt": (b"T" * 10, 500),         # 非图像，排除
    })
    items = list_recent_outputs(output_dir_of(root))
    rels = [i["rel"].replace("\\", "/") for i in items]
    assert rels == ["a.png", "sub/b.png", "c.jpg"]  # 新→旧
    assert all(i["size"] == 10 for i in items)
    assert list_recent_outputs(root / "ComfyUI" / "nope") == []


def test_archive_copies_to_dated_subfolder(tmp_path):
    root = _make_output(tmp_path, {"a.png": (b"A" * 10, 10)})
    target = tmp_path / "nas" / "图像"
    items = list_recent_outputs(output_dir_of(root))
    r = archive_files(items, target)
    assert len(r["copied"]) == 1 and not r["failed"]
    dest = Path(r["copied"][0]["dest"])
    assert dest.parent.name == time.strftime("%Y-%m-%d")   # 日期分夹
    assert dest.read_bytes() == b"A" * 10


def test_archive_additive_only(tmp_path):
    root = _make_output(tmp_path, {"a.png": (b"A" * 10, 10)})
    target = tmp_path / "nas"
    items = list_recent_outputs(output_dir_of(root))
    r1 = archive_files(items, target, date_subfolder=False)
    assert len(r1["copied"]) == 1
    # 同名同大小 → 跳过（绝不覆盖）
    r2 = archive_files(items, target, date_subfolder=False)
    assert len(r2["skipped"]) == 1 and not r2["copied"]
    assert (target / "a.png").read_bytes() == b"A" * 10


def test_archive_same_name_diff_size_renamed(tmp_path):
    root = _make_output(tmp_path, {"a.png": (b"NEW-CONTENT" * 3, 10)})
    target = tmp_path / "nas"
    (target).mkdir(parents=True)
    (target / "a.png").write_bytes(b"OLD")      # 同名不同大小
    items = list_recent_outputs(output_dir_of(root))
    r = archive_files(items, target, date_subfolder=False)
    assert len(r["renamed"]) == 1
    assert Path(r["renamed"][0]["dest"]).name == "a_2.png"
    assert (target / "a.png").read_bytes() == b"OLD"     # 原文件未动
    assert (target / "a_2.png").read_bytes() == b"NEW-CONTENT" * 3


def test_archive_unreachable_target_fails_clean(tmp_path):
    root = _make_output(tmp_path, {"a.png": (b"A", 10)})
    # 目标是文件的父级不可创建 → 整体失败、无半批拷贝
    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"x")
    r = archive_files(list_recent_outputs(output_dir_of(root)),
                      blocker / "sub" / "deeper")
    assert len(r["failed"]) == 1 and not r["copied"]


# ---------- CLI 契约 ----------

def _home_with_output(tmp_path: Path, mtime_offset: float = 0.0) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    root = _make_output(tmp_path, {"b.png": (b"B" * 5, mtime_offset)})
    cfg = {"schema_version": 1, "active_env_id": "e",
           "environments": [{"id": "e", "name": "E", "comfyui_root": str(root),
                             "python_path": "x"}],
           "launch": {}, "mirrors": {}}
    (home / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return home


def _run_cli(home: Path, *argv):
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
        code = cli_main(["--home", str(home), "--json", *argv])
    lines = [l for l in buf.getvalue().splitlines() if l.strip()]
    return code, (json.loads(lines[-1]) if lines else {})


def test_cli_archive_list_and_dryrun(tmp_path):
    home = _home_with_output(tmp_path)
    code, payload = _run_cli(home, "archive", "list")
    assert code == ec.EXIT_OK and payload["count"] == 1
    target = tmp_path / "nas2"
    code, payload = _run_cli(home, "archive", "run", "--all", "--dry-run",
                             "--target", str(target))
    assert code == ec.EXIT_OK and payload["dry_run"] is True
    assert not target.exists()          # dry-run 不落盘


def test_cli_archive_run_incremental(tmp_path):
    home = _home_with_output(tmp_path, mtime_offset=3600)   # 1小时前的旧图
    target = tmp_path / "nas3"
    code, payload = _run_cli(home, "archive", "run", "--target", str(target))
    assert code == ec.EXIT_OK and len(payload["copied"]) == 1
    # last_archive_at 已写 → 再跑增量 = 无新增
    code, payload = _run_cli(home, "archive", "run", "--target", str(target))
    assert code == ec.EXIT_OK and payload.get("note") == "自上次归档以来无新增"
    # --all 仍可全量，但同名同大小 → 跳过
    code, payload = _run_cli(home, "archive", "run", "--all", "--target", str(target))
    assert code == ec.EXIT_OK and len(payload["skipped"]) == 1


def test_cli_archive_run_offline_target(tmp_path):
    home = _home_with_output(tmp_path)
    blocker = tmp_path / "blocker"
    blocker.write_bytes(b"x")
    code, payload = _run_cli(home, "archive", "run", "--all",
                             "--target", str(blocker / "sub"))
    assert code == ec.EXIT_ERROR and len(payload["failed"]) == 1

"""三服务测试——用 tmp 真实 git 仓库（本地 bare 远端）验证，不 mock git。"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from wandao_launchpad.kernel import KernelService
from wandao_launchpad.model_paths import ModelPathsService, ModelLibrary
from wandao_launchpad.plugins import PluginService

_GIT_ENV = ["-c", "user.name=tester", "-c", "user.email=t@t"]


def _git(cwd: Path, *args: str, timeout: float = 30.0) -> str:
    r = subprocess.run(["git", *_GIT_ENV, *args], cwd=str(cwd), capture_output=True,
                       text=True, timeout=timeout,
                       creationflags=0x08000000)
    assert r.returncode == 0, f"git {args} 失败: {r.stderr}"
    return r.stdout


def _make_repo_with_remote(tmp: Path, name: str) -> tuple[Path, Path]:
    """建 bare 远端 + 克隆工作库，返回 (work, bare)。"""
    bare = tmp / f"{name}_origin.git"
    bare.mkdir()
    _git(bare, "init", "--bare", "-b", "main")
    work = tmp / name
    work.mkdir()
    _git(work, "init", "-b", "main")
    _git(work, "remote", "add", "origin", str(bare))
    _commit(work, "c0")
    _git(work, "push", "-u", "origin", "main")
    return work, bare


def _commit(repo: Path, msg: str) -> None:
    (repo / "_.txt").write_text(msg, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", msg)


def _push_upstream(bare: Path, tmp: Path, tag: str, msg: str) -> None:
    """模拟上游出新提交：第二个克隆里提交并推送（本地仓保持落后）。"""
    other = tmp / f"upstream_{tag}"
    _git(tmp, "clone", str(bare), str(other))
    _commit(other, msg)
    _git(other, "push", "origin", "main")


# ================= PluginService =================

def test_plugins_list_and_enable_disable(tmp_path):
    cn = tmp_path / "custom_nodes"
    cn.mkdir()
    (cn / "ComfyUI-Foo").mkdir()
    (cn / "ComfyUI-Bar.disabled").mkdir()
    (cn / "__pycache__").mkdir()
    svc = PluginService(cn)
    items = {p.name: p for p in svc.list()}
    assert set(items) == {"ComfyUI-Foo", "ComfyUI-Bar"}   # __pycache__ 排除
    assert items["ComfyUI-Bar"].enabled is False
    assert items["ComfyUI-Foo"].dir_name == "ComfyUI-Foo"

    info = svc.set_enabled("ComfyUI-Bar.disabled", True)
    assert info.enabled and info.dir_name == "ComfyUI-Bar"
    info = svc.set_enabled("ComfyUI-Bar", False)
    assert not info.enabled and info.dir_name == "ComfyUI-Bar.disabled"
    # 幂等：再禁一次不改名
    info = svc.set_enabled("ComfyUI-Bar.disabled", False)
    assert info.dir_name == "ComfyUI-Bar.disabled"


def test_plugins_check_updates_parallel_and_update(tmp_path):
    cn = tmp_path / "custom_nodes"
    cn.mkdir()
    # 两个 git 插件 + 一个本地插件
    p1, _ = _make_repo_with_remote(tmp_path, "node1")
    (cn / "node1").mkdir()
    subprocess.run(["robocopy", str(p1), str(cn / "node1"), "/E"],
                   capture_output=True)  # robocopy rc>=1 成功
    p2, bare2 = _make_repo_with_remote(tmp_path, "node2")
    (cn / "node2").mkdir()
    subprocess.run(["robocopy", str(p2), str(cn / "node2"), "/E"],
                   capture_output=True)
    (cn / "local-only").mkdir()

    svc = PluginService(cn)
    # 初始：都最新
    results = {r["dir_name"]: r for r in svc.check_updates()}
    assert results["node1"]["outdated"] is False
    assert results["node2"]["outdated"] is False
    assert "local-only" not in results

    # 远端 node2 出新提交 → outdated
    _commit(p2, "new upstream")
    _git(p2, "push", "origin", "main")
    results = {r["dir_name"]: r for r in svc.check_updates()}
    assert results["node2"]["outdated"] is True

    # update_all：node2 前进，node1 已是最新
    res = {r["dir_name"]: r for r in svc.update_all()}
    assert res["node2"]["ok"] is True
    results = {r["dir_name"]: r for r in svc.check_updates()}
    assert results["node2"]["outdated"] is False


def test_plugins_update_skips_dirty(tmp_path):
    cn = tmp_path / "custom_nodes"
    cn.mkdir()
    p1, bare1 = _make_repo_with_remote(tmp_path, "nodeD")
    (cn / "nodeD").mkdir()
    subprocess.run(["robocopy", str(p1), str(cn / "nodeD"), "/E"], capture_output=True)
    _commit(p1, "upstream change")
    _git(p1, "push", "origin", "main")
    # 用户改了现场（脏树）
    (cn / "nodeD" / "user_edit.txt").write_text("hand edit", encoding="utf-8")

    res = PluginService(cn).update_one("nodeD")
    assert res["ok"] is False and res["skipped"] is True
    assert "脏" in res["detail"]
    # 用户改动必须原样保留
    assert (cn / "nodeD" / "user_edit.txt").read_text(encoding="utf-8") == "hand edit"


# ================= KernelService =================

def _make_kernel(tmp: Path) -> tuple[KernelService, Path, Path]:
    work, bare = _make_repo_with_remote(tmp, "kernel")
    (work / "comfyui_version.py").write_text('__version__ = "0.42.0"', encoding="utf-8")
    _git(work, "add", "-A")
    _git(work, "commit", "-m", "version file")
    _git(work, "push", "origin", "main")
    _git(work, "tag", "v0.42.0")
    _git(work, "push", "origin", "v0.42.0")
    svc = KernelService(work, base_url=None)
    return svc, work, bare


def test_kernel_info_and_log(tmp_path):
    svc, work, _ = _make_kernel(tmp_path)
    info = svc.info()
    assert info.comfyui_version == "0.42.0"
    assert info.commit and not info.dirty
    rows = svc.log(count=5)
    assert 1 <= len(rows) <= 5
    assert rows[0]["subject"]


def test_kernel_update_already_latest(tmp_path):
    svc, work, bare = _make_kernel(tmp_path)
    result = svc.update()
    assert result["updated"] is False            # 已是最新 → 调用方映射退出码 4
    # 干跑不改动
    assert svc.update(dry_run=True)["updated"] is False


def test_kernel_update_ff(tmp_path):
    svc, work, bare = _make_kernel(tmp_path)
    _push_upstream(bare, tmp_path, "u1", "upstream1")
    result = svc.update()
    assert result["updated"] is True
    assert svc.info().commit in (result["to"] or "")


def test_kernel_update_refuses_when_running(tmp_path):
    svc, work, bare = _make_kernel(tmp_path)
    _push_upstream(bare, tmp_path, "u2", "up2")
    import wandao_launchpad.kernel as k
    orig = k.probe
    k.probe = lambda url, timeout=None: True
    try:
        running = KernelService(work, base_url="http://127.0.0.1:1")
        with pytest.raises(RuntimeError, match="运行"):
            running.update()
    finally:
        k.probe = orig


def test_kernel_update_refuses_dirty(tmp_path):
    svc, work, bare = _make_kernel(tmp_path)
    _push_upstream(bare, tmp_path, "u3", "up3")
    (work / "hand.txt").write_text("dirty", encoding="utf-8")
    with pytest.raises(RuntimeError, match="脏"):
        svc.update()


def test_kernel_stable_tag_and_checkout(tmp_path):
    svc, work, bare = _make_kernel(tmp_path)
    assert svc.latest_stable_tag() == "v0.42.0"
    # HEAD 就在标签上 → 稳定版更新应报"已是最新"
    plan = svc.update(dry_run=True, stable_only=True)
    assert plan["updated"] is False
    # 退回旧提交（模拟落后）→ 稳定版更新前进到标签
    _push_upstream(bare, tmp_path, "u4", "next dev")
    first = svc.log(count=10)[-1]["commit"]
    svc.checkout(first)
    plan = svc.update(dry_run=True, stable_only=True)
    assert plan["updated"] is True and plan["to"] == "v0.42.0"


# ================= ModelPathsService =================

def test_models_sidecar_roundtrip_and_scan(tmp_path):
    libroot = tmp_path / "mymodels"
    for sub in ("checkpoints", "loras", "随便放"):   # 含未知类型子目录
        (libroot / sub).mkdir(parents=True)
    cfg_dir = tmp_path / "home"
    cfg_dir.mkdir()
    svc = ModelPathsService(tmp_path, cfg_dir)

    svc.save_libraries([ModelLibrary(id="a", name="我的库",
                                     base_path=str(libroot))])
    libs = svc.load_libraries()
    assert libs[0].name == "我的库" and libs[0].base_path == str(libroot)

    maps = svc.scan_mappings(libs[0])
    assert maps == {"checkpoints": "checkpoints", "loras": "loras"}  # 未知类型不猜


def test_models_apply_renders_yaml_with_backup(tmp_path):
    comfy = tmp_path / "ComfyUI"
    comfy.mkdir()
    libroot = tmp_path / "libs"
    (libroot / "vae").mkdir(parents=True)
    cfg_dir = tmp_path / "home"
    cfg_dir.mkdir()
    svc = ModelPathsService(comfy, cfg_dir)

    # 预置一份"手写历史 yaml"→ apply 时应先备份
    old = comfy / "extra_model_paths.yaml"
    old.write_text("legacy:\n  base_path: X\n", encoding="utf-8")

    svc.save_libraries([
        ModelLibrary(id="a", name="库A", base_path=str(libroot)),
        ModelLibrary(id="b", name="库B", base_path="Z:/不存在", enabled=False),
    ])
    result = svc.apply()
    assert result["libraries"] == 1                 # 停用库不渲染
    assert result["backup"] and Path(result["backup"]).exists()

    import yaml
    data = yaml.safe_load(old.read_text(encoding="utf-8"))
    assert data["库A"]["base_path"] == str(libroot).replace("\\", "/") or \
        data["库A"]["base_path"] == str(libroot)
    assert data["库A"]["vae"] == "vae"
    assert "库B" not in data                          # 停用库不出现在 yaml


def test_models_import_existing(tmp_path):
    comfy = tmp_path / "ComfyUI"
    comfy.mkdir()
    (comfy / "extra_model_paths.yaml").write_text(
        "aki:\n  base_path: D:/models\n  checkpoints: ckpt/\n  is_python: true\n",
        encoding="utf-8")
    cfg_dir = tmp_path / "home"
    cfg_dir.mkdir()
    svc = ModelPathsService(comfy, cfg_dir)

    assert svc.import_existing() == 1
    libs = svc.load_libraries()
    assert libs[0].name == "aki"
    assert libs[0].base_path == "D:/models"
    # 值归一化为字符串、剥尾斜杠（yaml 的 true 是 bool）
    assert libs[0].mappings == {"checkpoints": "ckpt", "is_python": "True"}
    # sidecar 已存在 → 再 import 幂等为 0
    assert svc.import_existing() == 0


def test_models_validate(tmp_path):
    libroot = tmp_path / "good"
    (libroot / "loras").mkdir(parents=True)
    cfg_dir = tmp_path / "home"
    cfg_dir.mkdir()
    svc = ModelPathsService(tmp_path, cfg_dir)
    svc.save_libraries([
        ModelLibrary(id="a", name="好库", base_path=str(libroot),
                     mappings={"loras": "loras"}),
        ModelLibrary(id="b", name="坏库", base_path="Q:/ghost",
                     mappings={"不存在的类型": "x"}),
    ])
    problems = svc.validate()
    texts = "\n".join(problems)
    assert "Q:/ghost" in texts and "非法映射类型" in texts
    assert len(problems) == 2

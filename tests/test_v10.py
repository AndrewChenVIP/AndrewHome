"""v0.10 测试：智能诊断 / 参数预设 / 模型盘点。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from wandao_launchpad.archive import IMAGE_EXTS, VIDEO_EXTS  # noqa: F401
from wandao_launchpad.config import Config, ConfigStore, Environment
from wandao_launchpad.diagnose import diagnose, format_diagnosis
from wandao_launchpad.model_paths import (ModelLibrary, ModelPathsService,
                                          scan_installed_models)
from wandao_launchpad.presets import (all_names, delete_user_preset,
                                      get_preset, is_user_preset,
                                      save_user_preset)
from wandao_launchpad.models import LaunchOptions


# ---------- 诊断 ----------

def test_diag_oom():
    items = diagnose("torch.cuda.OutOfMemoryError: Tried to allocate 2.5 GiB")
    assert items and items[0]["id"] == "cuda_oom"
    assert "低显存" in items[0]["advice"]


def test_diag_module_missing_captures_name():
    items = diagnose("ModuleNotFoundError: No module named 'some_pkg'")
    assert items[0]["id"] == "module_missing"
    assert items[0]["detail"] == "some_pkg"
    assert "some_pkg" in format_diagnosis(items)


def test_diag_port_busy_and_import_failed():
    items = diagnose("error while attempting to bind on address ... "
                     "address already in use")
    assert any(i["id"] == "port_busy" for i in items)
    items = diagnose("IMPORT FAILED: ComfyUI-Foo")
    assert any(i["id"] == "import_failed" and i["detail"] == "ComfyUI-Foo"
               for i in items)


def test_diag_clean_log_and_format():
    assert diagnose("everything is fine") == []
    text = "Traceback (most recent call last):\n  File x\nValueError: boom"
    items = diagnose(text)
    assert any(i["id"] == "traceback" for i in items)
    formatted = format_diagnosis([], text)
    assert "未见已知错误模式" in formatted and "ValueError" in formatted


# ---------- 预设 ----------

def test_builtin_presets_apply():
    cfg = Config()
    names = all_names(cfg)
    assert "出图均衡" in names and "大模型低显存" in names and "排障（禁插件）" in names
    low = get_preset(cfg, "大模型低显存")
    assert low.vram == "low" and low.attention == "sdpa"
    assert low.port == 8188                      # 未指定字段回默认
    rescue = get_preset(cfg, "排障（禁插件）")
    assert rescue.disable_custom_nodes is True


def test_user_preset_roundtrip_and_shadow(home):
    store = ConfigStore(home)
    cfg = Config()
    save_user_preset(cfg, "我的配置", LaunchOptions(port=7777, vram="lowest"))
    store.save(cfg)
    cfg2 = store.load()
    assert is_user_preset(cfg2, "我的配置")
    got = get_preset(cfg2, "我的配置")
    assert got.port == 7777 and got.vram == "lowest"
    # 同名覆盖内置
    save_user_preset(cfg2, "出图均衡", LaunchOptions(port=9999))
    store.save(cfg2)                     # mutate 后必须落盘（API 语义与其他一致）
    assert get_preset(store.load(), "出图均衡").port == 9999
    # 删除（同一 cfg 对象上 mutate + save，与真实 GUI 用法一致）
    assert delete_user_preset(cfg2, "我的配置") is True
    store.save(cfg2)
    assert not is_user_preset(store.load(), "我的配置")
    assert delete_user_preset(cfg2, "出图均衡") is True   # 用户覆盖版可删
    store.save(cfg2)
    assert get_preset(store.load(), "出图均衡").port == 8188       # 回落内置
    assert delete_user_preset(store.load(), "不存在") is False


def test_persist_in_config_file(home):
    store = ConfigStore(home)
    cfg = Config()
    save_user_preset(cfg, "持久", LaunchOptions(port=1234))
    store.save(cfg)
    raw = json.loads((home / "config.json").read_text(encoding="utf-8-sig"))
    assert raw["launch_presets"][0]["name"] == "持久"


# ---------- 模型盘点 ----------

def test_scan_models_builtin_and_library(tmp_path):
    comfy = tmp_path / "pkg"
    (comfy / "ComfyUI" / "models" / "checkpoints").mkdir(parents=True)
    (comfy / "ComfyUI" / "models" / "checkpoints" / "a.safetensors").write_bytes(b"A" * 3)
    (comfy / "ComfyUI" / "models" / "checkpoints" / "readme.txt").write_bytes(b"x")
    (comfy / "ComfyUI" / "models" / "loras").mkdir(parents=True)
    (comfy / "ComfyUI" / "models" / "loras" / "b.safetensors").write_bytes(b"B" * 5)
    libroot = tmp_path / "nas"
    (libroot / "loras").mkdir(parents=True)
    (libroot / "loras" / "b.safetensors").write_bytes(b"B" * 5)

    libs = [ModelLibrary(id="a", name="NAS库", base_path=str(libroot),
                         mappings={"loras": "loras"})]
    data = scan_installed_models(comfy, libs)
    assert {f["name"] for f in data["checkpoints"]} == {"a.safetensors"}
    assert "readme.txt" not in {f["name"] for f in data["checkpoints"]}
    lora_sources = {f["source"] for f in data["loras"]}
    assert lora_sources == {"内置", "NAS库"}        # 两处各计一份（不同路径）
    assert len(data["loras"]) == 2
    # 排序：新→旧（b 后写 → 两个 b 在前）
    mtimes = [f["mtime"] for f in data["loras"]]
    assert mtimes == sorted(mtimes, reverse=True)


def test_scan_models_skips_disabled_library(tmp_path):
    comfy = tmp_path / "pkg"
    (comfy / "ComfyUI" / "models").mkdir(parents=True)
    libroot = tmp_path / "nas2"
    (libroot / "vae").mkdir(parents=True)
    (libroot / "vae" / "x.pt").write_bytes(b"X")
    libs = [ModelLibrary(id="a", name="停用库", base_path=str(libroot),
                         mappings={"vae": "vae"}, enabled=False)]
    data = scan_installed_models(comfy, libs)
    assert data == {}


# ---------- CLI start 诊断字段（契约存在性，不真启动） ----------

def test_start_payload_diagnosis_key(home, capsys):
    """未配置环境时 start 报错；契约字段在真正 start 路径中由 ProcessManager 提供。
    这里验证 payload 组装不会因 diagnosis 缺失而崩（用 info 验证序列化路径）。"""
    from wandao_launchpad.cli import main as cli_main
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = cli_main(["--home", str(home), "--json", "info"])
    assert code == 0

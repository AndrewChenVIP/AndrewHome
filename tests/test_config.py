from __future__ import annotations

import json

from wandao_launchpad.config import Config, ConfigStore, Environment


def test_missing_file_gives_defaults(home):
    cfg = ConfigStore(home).load()
    assert cfg.environments == []
    assert cfg.launch.port == 8188


def test_roundtrip_preserves_everything(home):
    store = ConfigStore(home)
    cfg = Config()
    cfg.environments.append(Environment(id="a", name="甲", comfyui_root="R", python_path="P"))
    cfg.active_env_id = "a"
    cfg.launch.port = 9999
    cfg.launch.env_vars = {"K": "V"}
    cfg._extras = {"future_field": [1, 2]}  # 前向兼容袋
    store.save(cfg)

    loaded = store.load()
    assert loaded.launch.port == 9999
    assert loaded.launch.env_vars == {"K": "V"}
    assert loaded.active_env().name == "甲"
    assert loaded._extras["future_field"] == [1, 2]


def test_bad_json_falls_back(home):
    (home / "config.json").write_text("{oops", encoding="utf-8")
    cfg = ConfigStore(home).load()
    assert cfg.launch.port == 8188


def test_active_env_fallback_to_first(home):
    store = ConfigStore(home)
    cfg = Config()
    cfg.environments = [Environment(id="a"), Environment(id="b")]
    cfg.active_env_id = "ghost"  # 指向不存在的 id
    store.save(cfg)
    assert store.load().active_env_id == "a"


def test_atomic_write_no_tmp_left(home):
    store = ConfigStore(home)
    store.save(Config())
    leftovers = [p.name for p in home.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []
    raw = json.loads((home / "config.json").read_text(encoding="utf-8-sig"))
    assert raw["schema_version"] == 1


def test_update_launch_locked_mutate(home):
    store = ConfigStore(home)
    store.save(Config())
    store.update_launch(lambda o: setattr(o, "port", 7777))
    assert store.load().launch.port == 7777

"""启动参数预设——内置三套 + 用户自存，一键切换整套启动选项。

预设存 config extras["launch_presets"]（与主题/落点同一人读区）。
同名时用户预设覆盖内置。
"""
from __future__ import annotations

from .config import Config
from .models import LaunchOptions

# 内置预设：字段缺省 = 用出厂默认值
BUILTIN_PRESETS: dict[str, dict] = {
    "出图均衡": {},
    "大模型低显存": {"vram": "low", "attention": "sdpa",
                    "fast_fp16_accumulation": True},
    "排障（禁插件）": {"disable_custom_nodes": True, "auto_open_browser": False},
}

_PRESETS_KEY = "launch_presets"


def _user_presets(cfg: Config) -> list[dict]:
    v = cfg._extras.get(_PRESETS_KEY)
    return [p for p in v if isinstance(p, dict) and "name" in p] \
        if isinstance(v, list) else []


def all_names(cfg: Config) -> list[str]:
    """内置在前、用户在后；同名用户覆盖内置（列表只出现一次）。"""
    user = [p["name"] for p in _user_presets(cfg)]
    names = list(BUILTIN_PRESETS.keys())
    for n in user:
        if n in names:
            names[names.index(n)] = n
        else:
            names.append(n)
    return names


def get_preset(cfg: Config, name: str) -> LaunchOptions | None:
    for p in _user_presets(cfg):
        if p["name"] == name:
            return LaunchOptions.from_dict(p.get("options"))
    if name in BUILTIN_PRESETS:
        merged = {**LaunchOptions().to_dict(), **BUILTIN_PRESETS[name]}
        return LaunchOptions.from_dict(merged)
    return None


def save_user_preset(cfg: Config, name: str, options: LaunchOptions) -> None:
    name = name.strip()
    if not name:
        raise ValueError("预设名不能为空")
    presets = [p for p in _user_presets(cfg) if p["name"] != name]
    presets.append({"name": name, "options": options.to_dict()})
    cfg._extras[_PRESETS_KEY] = presets


def delete_user_preset(cfg: Config, name: str) -> bool:
    """删用户预设；内置预设不可删（返回 False）。"""
    presets = _user_presets(cfg)
    kept = [p for p in presets if p["name"] != name]
    if len(kept) == len(presets):
        return False
    cfg._extras[_PRESETS_KEY] = kept
    return True


def is_user_preset(cfg: Config, name: str) -> bool:
    return any(p["name"] == name for p in _user_presets(cfg))

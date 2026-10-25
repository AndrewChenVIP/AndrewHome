"""镜像三件套——HF / GitHub / PyPI 的国内加速配置。"""

from __future__ import annotations

from .config import Mirrors
from .constants import DEFAULT_HF_MIRROR


def mirror_env_vars(mirrors: Mirrors) -> dict[str, str]:
    """注入给 ComfyUI 子进程的环境变量（只含非空项）。"""
    env: dict[str, str] = {}
    hf = (mirrors.hf or "").strip()
    if not hf:
        hf = DEFAULT_HF_MIRROR
    env["HF_ENDPOINT"] = hf
    if (mirrors.github_proxy or "").strip():
        # GitPython / 部分工具识别的通用前缀变量；启动器自身克隆时也用它
        env["WANDAO_GH_PROXY"] = mirrors.github_proxy.strip()
    return env


def pip_index_url(pypi_key_or_url: str) -> str | None:
    """pip 镜像解析：接受 tuna/aliyun/huawei 别名或完整 URL；空返回 None。"""
    from .constants import PIP_MIRRORS

    key = pypi_key_or_url.strip()
    if not key:
        return None
    return PIP_MIRRORS.get(key, key)

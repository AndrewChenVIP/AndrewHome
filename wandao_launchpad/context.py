"""AppContext——GUI 与 CLI 共享的运行上下文。

教训对策（Mie 的 HeadlessAppContext 手工镜像 40+ 属性、两边漂移）：
- 上下文是一个显式 dataclass，GUI/CLI 用同一条路径从 ConfigStore 构造。
- 服务函数只收 AppContext / 显式入参，不认识任何 UI 对象。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Config, Environment
from .models import LaunchOptions


@dataclass(frozen=True)
class AppContext:
    """一次操作所需的全部世界状态。不可变——换环境就换一个新实例。"""

    config: Config
    env: Environment
    launch: LaunchOptions

    # --- 派生路径（唯一实现，全项目经此取，不许各自拼） ---
    @property
    def comfyui_root(self) -> Path:
        return Path(self.env.comfyui_root)

    @property
    def main_script(self) -> Path:
        if self.env.main_script:
            return self.comfyui_root / self.env.main_script
        cand = self.comfyui_root / "ComfyUI" / "main.py"
        if cand.exists():
            return cand
        return self.comfyui_root / "main.py"

    @property
    def python_exe(self) -> str:
        return self.env.python_path or "python"

    @property
    def port(self) -> int:
        return self.launch.port

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def comfyui_log(self) -> Path:
        # ComfyUI 约定：<root>/user/comfyui.log；探测不到就落 root 下
        user_dir = self.comfyui_root / "ComfyUI" / "user"
        if (user_dir).exists() or (self.comfyui_root / "user").exists():
            base = user_dir if user_dir.exists() else self.comfyui_root / "user"
            return base / "comfyui.log"
        return self.comfyui_root / "comfyui.log"


def build_context(cfg: Config, env_id: str | None = None) -> AppContext:
    """从 Config 构造 AppContext。CLI 的 --env 与 GUI 激活环境走同一个函数。"""
    target_id = env_id or cfg.active_env_id
    env = None
    for candidate in cfg.environments:
        if candidate.id == target_id:
            env = candidate
            break
    if env is None:
        raise LookupError(f"环境不存在: {target_id!r}（可用: {[e.id for e in cfg.environments]}）")
    return AppContext(config=cfg, env=env, launch=cfg.launch)

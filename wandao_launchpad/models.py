"""启动选项模型——表单 ↔ ComfyUI CLI 旗标映射的唯一事实来源。

字段增删只改这里和 command_builder.py 的映射表，GUI 表单和 CLI 均从这里取默认值。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

VRAM_CHOICES = ("auto", "high", "normal", "low", "lowest")
ATTENTION_CHOICES = ("auto", "sdpa", "flash", "sage", "split", "quad")
MODE_CHOICES = ("gpu", "cpu")


@dataclass
class LaunchOptions:
    # 运行模式与网络
    mode: str = "gpu"                 # gpu | cpu
    port: int = 8188
    listen_lan: bool = False
    # 显存策略（auto = 不传旗标，交给 ComfyUI 自判）
    vram: str = "auto"
    # 注意力实现
    attention: str = "auto"
    # 指定 GPU（None = 不指定）；实现为 CUDA_VISIBLE_DEVICES 环境变量
    gpu_index: int | None = None
    # 杂项旗标
    fast_fp16_accumulation: bool = False
    disable_custom_nodes: bool = False
    windows_standalone: bool = True   # 便携式 python_embeded 需要 --windows-standalone-build
    # 浏览器
    auto_open_browser: bool = True
    browser_path: str = ""            # 空 = 默认浏览器
    # 自由区
    extra_args: str = ""              # 原样追加
    env_vars: dict[str, str] = field(default_factory=dict)

    def validate(self) -> list[str]:
        errs: list[str] = []
        if self.mode not in MODE_CHOICES:
            errs.append(f"mode 必须是 {MODE_CHOICES}，当前 {self.mode!r}")
        if not (1 <= self.port <= 65535):
            errs.append(f"port 越界: {self.port}")
        if self.vram not in VRAM_CHOICES:
            errs.append(f"vram 必须是 {VRAM_CHOICES}，当前 {self.vram!r}")
        if self.attention not in ATTENTION_CHOICES:
            errs.append(f"attention 必须是 {ATTENTION_CHOICES}，当前 {self.attention!r}")
        if self.gpu_index is not None and self.gpu_index < 0:
            errs.append(f"gpu_index 不能为负: {self.gpu_index}")
        return errs

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict | None) -> "LaunchOptions":
        """宽松装载：未知字段忽略，缺省字段取默认——配置文件落后于代码时不炸。"""
        opts = cls()
        if not raw:
            return opts
        known = {f for f in opts.to_dict()}
        for key, val in (raw or {}).items():
            if key in known:
                setattr(opts, key, val)
        return opts

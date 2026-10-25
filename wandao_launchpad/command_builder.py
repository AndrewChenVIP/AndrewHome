"""命令构建器——LaunchOptions → argv + env。纯函数，无 IO。

旗标映射的唯一事实来源。ComfyUI 升级改旗标，只改这里 + 对应测试。
"""

from __future__ import annotations

import shlex

from .context import AppContext

_VRAM_FLAGS = {
    "high": "--highvram",
    "normal": "--normalvram",
    "low": "--lowvram",
    "lowest": "--novram",
}

_ATTENTION_FLAGS = {
    "sdpa": "--use-pytorch-cross-attention",
    "flash": "--use-flash-attention",
    "sage": "--use-sage-attention",
    "split": "--use-split-cross-attention",
    "quad": "--use-quad-cross-attention",
}


def build_argv(ctx: AppContext) -> list[str]:
    opts = ctx.launch
    argv = [ctx.python_exe, str(ctx.main_script)]
    if opts.mode == "cpu":
        argv.append("--cpu")
    argv += ["--port", str(opts.port)]
    if opts.listen_lan:
        argv.append("--listen")
    if opts.vram in _VRAM_FLAGS:
        argv.append(_VRAM_FLAGS[opts.vram])
    if opts.attention in _ATTENTION_FLAGS:
        argv.append(_ATTENTION_FLAGS[opts.attention])
    if opts.fast_fp16_accumulation:
        argv.append("--fast-fp16-accumulation")
    if opts.disable_custom_nodes:
        argv.append("--disable-all-custom-nodes")
    if opts.windows_standalone:
        argv.append("--windows-standalone-build")
    if opts.extra_args.strip():
        argv += shlex.split(opts.extra_args, posix=False)
    return argv


def build_env(ctx: AppContext, base_environ: dict[str, str] | None = None) -> dict[str, str]:
    """合并顺序：系统环境 < 镜像三件套 < 显式 env_vars < GPU 指定（最后写，保证生效）。"""
    import os

    from .network import mirror_env_vars

    env = dict(os.environ if base_environ is None else base_environ)
    env.update(mirror_env_vars(ctx.config.mirrors))
    env.update({str(k): str(v) for k, v in ctx.launch.env_vars.items()})
    if ctx.launch.gpu_index is not None:
        env["CUDA_VISIBLE_DEVICES"] = str(ctx.launch.gpu_index)
    return env

from __future__ import annotations

from pathlib import Path

from wandao_launchpad.config import Config, Environment, Mirrors
from wandao_launchpad.context import AppContext, build_context
from wandao_launchpad.command_builder import build_argv, build_env


def _ctx(tmp_path, **launch_kw) -> AppContext:
    root = tmp_path / "pkg"
    (root / "ComfyUI").mkdir(parents=True, exist_ok=True)
    (root / "ComfyUI" / "main.py").write_text("", encoding="utf-8")
    cfg = Config(
        active_env_id="e1",
        environments=[Environment(id="e1", name="t", comfyui_root=str(root),
                                  python_path="C:/py/python.exe")],
    )
    from wandao_launchpad.models import LaunchOptions
    opts = LaunchOptions(**launch_kw)
    cfg.launch = opts
    return build_context(cfg)


def test_default_gpu(tmp_path):
    argv = build_argv(_ctx(tmp_path))
    assert argv[0] == "C:/py/python.exe"
    assert argv[1].endswith("ComfyUI\\main.py") or argv[1].endswith("ComfyUI/main.py")
    assert "--port" in argv and "8188" in argv
    assert "--cpu" not in argv
    assert "--windows-standalone-build" in argv  # 默认便携模式
    assert "--listen" not in argv


def test_cpu_and_lan(tmp_path):
    argv = build_argv(_ctx(tmp_path, mode="cpu", listen_lan=True))
    assert "--cpu" in argv and "--listen" in argv


def test_vram_mapping(tmp_path):
    assert "--highvram" in build_argv(_ctx(tmp_path, vram="high"))
    assert "--novram" in build_argv(_ctx(tmp_path, vram="lowest"))
    assert "--normalvram" in build_argv(_ctx(tmp_path, vram="normal"))
    assert "--lowvram" in build_argv(_ctx(tmp_path, vram="low"))
    for bad in ("highvram", "--highvram"):
        argv = build_argv(_ctx(tmp_path, vram="auto"))
        assert bad not in argv


def test_attention_mapping(tmp_path):
    assert "--use-sage-attention" in build_argv(_ctx(tmp_path, attention="sage"))
    assert "--use-pytorch-cross-attention" in build_argv(_ctx(tmp_path, attention="sdpa"))
    assert "--use-split-cross-attention" in build_argv(_ctx(tmp_path, attention="split"))
    assert "--use-quad-cross-attention" in build_argv(_ctx(tmp_path, attention="quad"))
    assert "--use-flash-attention" in build_argv(_ctx(tmp_path, attention="flash"))
    assert not any(a.startswith("--use-") for a in build_argv(_ctx(tmp_path, attention="auto")))


def test_misc_flags_and_extra(tmp_path):
    argv = build_argv(_ctx(tmp_path, fast_fp16_accumulation=True,
                           disable_custom_nodes=True, extra_args="--fp16-vae --disable-smart-memory"))
    assert "--fast-fp16-accumulation" in argv
    assert "--disable-all-custom-nodes" in argv
    assert "--fp16-vae" in argv and "--disable-smart-memory" in argv


def test_gpu_index_env_wins(tmp_path):
    cfg_env = {"CUDA_VISIBLE_DEVICES": "0", "MY_VAR": "1"}
    env = build_env(_ctx(tmp_path, gpu_index=2, env_vars={"MY_VAR": "2"}),
                    base_environ=cfg_env)
    assert env["CUDA_VISIBLE_DEVICES"] == "2"      # GPU 指定最后写，必须赢
    assert env["MY_VAR"] == "2"                     # 显式 env_vars 覆盖系统
    assert env["HF_ENDPOINT"]                       # 镜像默认注入


def test_mirror_env_override(tmp_path):
    from wandao_launchpad.config import Config as C
    cfg = C()
    cfg.mirrors = Mirrors(hf="https://my-hf.example")
    ctx = AppContext(config=cfg, env=Environment(id="x", name="x"),
                     launch=cfg.launch)
    env = build_env(ctx, base_environ={})
    assert env["HF_ENDPOINT"] == "https://my-hf.example"


def test_main_script_resolution_prefers_comfyui_subdir(tmp_path):
    root = tmp_path / "pkg2"
    (root / "ComfyUI").mkdir(parents=True)
    (root / "ComfyUI" / "main.py").write_text("", encoding="utf-8")
    cfg = Config(active_env_id="e",
                 environments=[Environment(id="e", name="e", comfyui_root=str(root))])
    ctx = build_context(cfg)
    assert ctx.main_script == Path(root) / "ComfyUI" / "main.py"

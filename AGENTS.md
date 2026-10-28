# AGENTS.md — 万道启动台 WandaoLaunchpad（给接任 Agent 的第一站）

万道自研 ComfyUI 启动器：**只做编排器不分叉内核**。当前 **v0.10.1**（2026-10-29 重启开发，
109/109 测试全绿，HEAD 见 git log）。完整入口：`docs/交接文档-v0.10.0.md`。

## 常用命令（逐条可复制）

```bash
pip install -e .[test]                                  # 装依赖（含 pytest）
pytest                                                  # 全量测试（必须全绿才许提交）
python -m wandao_launchpad gui                          # 图形界面
python -m wandao_launchpad status --json                # 0=在跑 1=异常 3=未跑
python -m wandao_launchpad start / stop / restart       # 启停（失败自动附 diagnosis）
python -m wandao_launchpad plugins list|search|install|check-updates|update-all
python -m wandao_launchpad kernel info|update --sync-deps|log|checkout
python -m wandao_launchpad models list|import|validate|apply
python -m wandao_launchpad doctor [--quick]             # 八项体检
python -m wandao_launchpad archive list|run [--all --dry-run]
python -m wandao_launchpad support --out xx.zip         # 排障支持包
python scripts/build.py                                 # 打包 → dist/（onedir 64MB）
```

## 目录地图

- `wandao_launchpad/` 核心层（config/models/context/pidfile/process_manager/probe/pipx/
  plugins/kernel/model_paths/diagnose/presets/archive/autostart/support）——**禁 import PyQt5**
- `wandao_launchpad/cli/` 子命令 + exitcodes 契约；`wandao_launchpad/gui/` PyQt5 界面
- `tests/` 104 项（单测 + 假 ComfyUI 生命周期 e2e + 架构守卫）；`scripts/` build 与假 ComfyUI

## 铁律（tests/test_arch_guard.py 有守卫，违反即红灯）

1. core 层禁 import PyQt5；2. 禁裸 `except: pass`（吞异常必须留日志）；
3. 同一逻辑只留一份实现；4. 杀进程定点单次验尸，禁按端口扫射、禁静默提权；
5. 主线程零重活（子进程/网络/大文件全进 worker）；6. AppContext 唯一共享上下文，
服务函数不许摸 UI 对象。另：**pip 永不触碰 torch/torchvision/torchaudio/triton**
（CUDA 冻结保护，pipx.FROZEN_PKGS）；测试端口用 18999 避让真机 8188。

## 重启路径

1. `pytest` 全绿确认环境 → 2. 读 `docs/交接文档-v0.10.0.md` → 3. 按其第 6 节技术债清单选题
→ 4. 沿用"红绿循环 + GUI offscreen 冒烟 + 版本三处同步（__init__/pyproject/README）"工作法。

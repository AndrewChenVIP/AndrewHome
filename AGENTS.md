# AGENTS.md — 给 AI agent 的操作契约

## 这是什么

万道启动台（WandaoLaunchpad）：万道自研 ComfyUI 启动器，PyQt5 GUI + headless CLI 同体。
对标分析对象是 Mie 启动器（NAS 05Agent工具库\02开源工具\ComfyUI-Mie-Package-Launcher，
分析报告见 08Agent归档中心 2026-10-26 两份）——本项目是"吸取其教训从零重写"的产物。

## agent 怎么用

```bash
python -m wandao_launchpad status --json   # 判断在不在跑：0=在跑 3=未跑 1=异常
python -m wandao_launchpad start           # 阻塞到就绪；已在跑退 2
python -m wandao_launchpad stop            # 幂等；作用于当前在跑的实例
python -m wandao_launchpad info --json     # 看生效配置，不启动任何东西
python -m wandao_launchpad logs comfyui -n 100   # 务必默认 no-follow（-f 会阻塞）
```

- 按**退出码 + 单行 JSON** 分支，不要正则匹配人类文案。
- 退出码定义在 `wandao_launchpad/cli/exitcodes.py`，语义冻结。
- 配置目录：环境变量 `WANDAO_LAUNCHPAD_HOME` 或默认 `<项目>/launchpad/`（含本机绝对路径，**禁止提交进 git**）。

## 改代码前必读（本项目六条铁律，tests/test_arch_guard.py 有守卫）

1. **core 层禁止 import PyQt5**——UI 依赖只许出现在 `gui/`。
2. **禁止裸 `except: pass`**——吞异常必须留日志（至少 logger.debug）。
3. **同一逻辑只留一份实现**——pidfile/配置读写/旗标映射/版本解析各只有一处正本。
4. **杀进程永远定点、单次、验尸**——禁止按端口扫描杀、禁止重复补刀、禁止静默提权。
5. **主线程零重活**——子进程/网络/大文件一律进 worker 线程；UI 只收信号。
6. **AppContext 是唯一共享上下文**——服务函数只收入参/AppContext，不许摸 UI 对象，
   不许给 headless 造"属性镜像替身"（Mie 的 HeadlessAppContext 漂移教训）。

## 常见坑

- `logs -f` 永久阻塞，自动化禁用。
- `start` 已在跑时退 2 并返回 `running_env_id`——先 `stop` 再动。
- 配置文件里 `launch.extra_args` 原样追加到命令行（shlex posix=False，Windows 路径安全）。
- 旗标映射（显存/注意力→ComfyUI 参数）只在 `command_builder.py`，改映射同步改测试。

## 测试

`pytest` 全绿才许收工；生命周期 e2e 用 `scripts/fake_comfyui.py` 当假 ComfyUI，
不碰真实安装。

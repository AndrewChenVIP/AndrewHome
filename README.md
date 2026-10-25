# 万道启动台 WandaoLaunchpad

万道自研的 ComfyUI 启动器：**只做编排器，不分叉 ComfyUI 内核**——拼参数、起进程、管配置，其余一切挂 ComfyUI 生态既有扩展点。

- **GUI 与 CLI 同体**：无参数启动 = 图形界面；带子命令 = headless CLI，两者复用同一套核心层。
- **契约稳定**：每个 CLI 命令支持 `--json` 单行输出 + 集中定义的退出码，外部脚本与 AI agent 按契约消费。
- **进程管理严谨**：pidfile 带 create_time 身份校验（防 PID 复用误判）；杀进程一条链（优雅 → 验尸 → 强杀一次 → 验尸），绝不重复补刀、绝不按端口扫射、绝不静默提权。
- **主线程零重活**：GUI 里所有子进程/网络/文件操作都在 QThread worker 里，表单自动保存带 500ms 防抖。

## 快速开始

```bash
pip install -r requirements.txt

# CLI（先在设置里配好环境，或直接编辑 launchpad/config.json）
python -m wandao_launchpad status --json     # 0=在跑 / 3=未跑 / 1=异常
python -m wandao_launchpad start             # 阻塞到 /system_stats 就绪
python -m wandao_launchpad stop              # 幂等
python -m wandao_launchpad info --json       # 查看生效配置
python -m wandao_launchpad logs comfyui -n 100

# GUI
python -m wandao_launchpad gui
```

## 退出码契约（稳定，勿改）

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 1 | 通用错误（配置缺失/路径/IO/超时；`models validate` 发现问题） |
| 2 | start 拒绝重复启动（本启动台实例在跑，或端口被外部实例占用 `external:true`） |
| 3 | status：未运行 |
| 4 | kernel update：已是最新，无变更 |

## 管理三件套（v0.2）

```bash
# 插件：list / enable NAME / disable NAME / uninstall NAME --yes / check-updates / update [NAME] / update-all
python -m wandao_launchpad plugins list --json
python -m wandao_launchpad plugins check-updates     # 并行（8 worker）git 检查
python -m wandao_launchpad plugins update-all        # 只对干净树 pull --ff-only；脏树跳过不动现场

# 内核：info / update [--stable-only --dry-run] / log [-n N --skip S] / checkout REF --yes
python -m wandao_launchpad kernel info               # 版本 + 提交 + 脏树标记
python -m wandao_launchpad kernel update --dry-run   # 先看会做什么
# 写操作前置拒绝：ComfyUI 运行中（端口真相）/ 内核树脏

# 外置模型库：list / import / validate / apply
python -m wandao_launchpad models import             # 把现有 extra_model_paths.yaml 导入托管
python -m wandao_launchpad models apply              # sidecar 渲染 yaml（旧文件先备份）
```

- 插件启停沿用 ComfyUI-Manager 的 `.disabled` 目录后缀约定。
- 模型库唯一真源是 sidecar（`launchpad/model_libs.json`），yaml 是渲染产物；路径含 `#`/中文/空格都由 PyYAML 保证不坏。

> **端口真相原则**：status 以 `/system_stats` 是否应答判断"在跑"，以 pidfile 判断"是不是我们起的"。
> 外部实例（别的启动器/手动启动）在跑时 status 如实上报（`external:true`），stop **绝不会**杀它。

## 目录结构

```
wandao_launchpad/
├── models.py           # LaunchOptions——表单↔旗标映射的唯一事实来源
├── command_builder.py  # 选项 → argv/env（纯函数）
├── config.py           # ConfigStore——配置唯一入口（原子写/多环境/前向兼容）
├── context.py          # AppContext——GUI/CLI 共享上下文（显式协议，禁止镜像属性）
├── pidfile.py          # 唯一 pidfile 实现（create_time 身份校验）
├── process_manager.py  # 进程生命周期唯一 owner
├── probe.py            # /system_stats 就绪探测
├── network.py          # 镜像三件套（HF/GitHub/PyPI）
├── cli/                # 子命令 + 退出码契约
└── gui/                # PyQt5 界面（workers/防抖表单/日志视图/主题token）
```

## 开发

```bash
pip install -e .[test]
pytest            # 38 项测试：单测 + 假 ComfyUI 生命周期 e2e + 架构守卫
```

架构铁律（有测试守卫，见 `tests/test_arch_guard.py`）：
1. core 层禁止 import PyQt5；
2. 全项目禁止裸 `except: pass`；
3. 同一逻辑只留一份实现。

## License

Apache-2.0

# 万道启动台 WandaoLaunchpad

> **v0.10.1**（2026-10-29 重启开发）· 109/109 测试全绿 · 交接入口见 `docs/交接文档-v0.10.0.md`

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

## 插件搜索与安装（v0.3）

```bash
python -m wandao_launchpad plugins search animate    # 搜官方 custom-node-list（1h 缓存；直连→代理→CDN 三通道，全挂降级过期缓存）
python -m wandao_launchpad plugins install ComfyUI-KJNodes   # 按名安装（清单解析）
python -m wandao_launchpad plugins install https://github.com/xxx/yyy  # 或直接 git URL
```

## 打包（v0.3）

```bash
pip install pyinstaller
python scripts/build.py       # → dist/WandaoLaunchpad/（onedir，裁剪后约 64MB）+ dist/万道启动台.cmd
```

- onedir 而非 onefile（onefile 每次启动解压慢——Mie 113MB 的教训）。
- 体积裁剪：Mesa 软渲染 DLL（20MB）、Qt Quick/Qml 系、翻译文件全砍（对标分析同款冗余）。
- 便携原则：配置目录跟 exe 走（`WandaoLaunchpad/launchpad/`），exe 放哪配置在哪。

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

AGPL-3.0（随仓库主 AndrewHome 初始提交定夺）

## 多环境与主题（v0.4）

- 启动页顶部队拉快切环境；本启动台实例运行中会拒绝切换（先停止）。
- 设置页：环境列表新增/复制/删除（至少保留一个）/设激活；深浅主题切换实时生效并持久化。
- `info --env <id>` 按指定环境解析路径；未知 id 退 1（不再静默回退）。

## 支持包与开机自启（v0.5）

```bash
python -m wandao_launchpad support            # 打包排障 zip（info+启动器日志+comfyui日志尾部）到配置目录
```

开机自启（Windows 任务计划，登录后自动拉起 ComfyUI 并等就绪）：

```cmd
schtasks /Create /TN "WandaoLaunchpad" /SC ONLOGON /TR "C:\...\WandaoLaunchpad.exe start --no-wait"
schtasks /Delete /TN "WandaoLaunchpad" /F     # 取消
```

监控存活（每 5 分钟探一次，没跑就拉起）：

```cmd
schtasks /Create /TN "WandaoLaunchpadWatch" /SC MINUTE /MO 5 /TR "C:\...\WandaoLaunchpad.exe status || C:\...\WandaoLaunchpad.exe start --no-wait"
```

GUI：关闭窗口可最小化到系统托盘（设置页开关）；托盘菜单含"退出并关闭 ComfyUI"。

## 依赖联动与体检（v0.7）

```bash
python -m wandao_launchpad doctor              # 八项体检（python/入口/端口/磁盘/pip/内核/yaml/模型库）
python -m wandao_launchpad doctor --quick      # 快检查（无子进程；启动预检同款）
python -m wandao_launchpad plugins install X   # 装完自动装插件 requirements.txt
python -m wandao_launchpad kernel update --sync-deps   # 更新内核后同步 requirements
```

- `--no-deps` 可跳过插件依赖安装；`install/update` 后有 requirements 才触发。
- **CUDA 冻结保护**：`torch / torchvision / torchaudio / triton` 永远不被 pip 触碰
  （内核依赖同步只做 only-if-needed 升级，冻结包先行剔除）——保护手工调好的 CUDA 栈。
- GUI：启动页「🩺 体检」按钮；点「一键启动」自动先跑快体检，阻塞项直接拦截；
  内核页「同步依赖库」勾选。

## 出图归档（v0.8，万道特色）

```bash
python -m wandao_launchpad archive list            # 列 output 里的图像（新→旧）
python -m wandao_launchpad archive run --dry-run   # 预览将归档什么（默认：自上次以来新增）
python -m wandao_launchpad archive run --all       # 全量归档
```

- 落点出厂值 `\100.108.142.97\Accumulation\WandaoOS\06AIGC作品库\图像`，设置页可改。
- **只增不删**：按日期分夹落库（图像/2026-10-26/…）；同名同大小视为已归档跳过；
  同名不同大小自动改名续位（a_2.png），绝不覆盖 NAS 已有文件。
- GUI「📤 归档」页：勾选式批量归档，"选新增（自上次归档）"一键筛选；
  仅处理图像（png/jpg/webp/gif/bmp），视频暂不归档。

## 视频归档 / 自动看门 / 开机自启（v0.9）

- 归档页新增**视频区**（落点默认 `06AIGC作品库\视频`，设置可改），图像/视频切换；
  图像区升级为**缩略图网格**，看得见图再勾选。
- **自动归档看门**（设置页开关，默认关）：新图落定（大小稳定 3 秒）即自动入 NAS，
  托盘气泡提示；失败自动退避 60 秒重试，绝不产生半写归档。
- **开机自启**（设置页一键注册/取消，便携版限定）：登录后拉起启动台，
  任务名 `WandaoLaunchpadGUI`。

## 智能诊断 / 参数预设 / 模型浏览（v0.10）

- **启动失败智能诊断**：启动超时或 ComfyUI 意外退出时，自动抓日志尾部匹配已知模式
  （显存不足 / 缺模块 / 端口占用 / 前端不匹配 / 插件加载失败 / Torch-CUDA 不匹配 / 驱动过旧
  / DLL 损坏），给出"出了什么事 + 建议动作"；未命中则展示日志尾部原样。
  CLI `start` 失败时 payload 带 `diagnosis` 字段。
- **参数预设档**：启动页顶部下拉切换；内置「出图均衡 / 大模型低显存 / 排障（禁插件）」，
  可把当前表单"存为预设"（同名覆盖内置）或删除；存 config extras，随配置走。
- **模型浏览页**（🗃 导航）：按类型盘点内置 models 与各挂载库的模型文件
  （名称/大小/日期/来源库），双击打开所在文件夹。
- 托盘新增「归档全部新增」「打开最新出图」；窗口位置尺寸记忆。

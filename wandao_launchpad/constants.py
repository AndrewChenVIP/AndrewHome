"""全项目唯一的魔数集中地。散落的魔法数字 = 未来漂移的开始。"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "万道启动台"
APP_ID = "WandaoLaunchpad"

# --- 进程生命周期 ---
DEFAULT_PORT = 8188
PROBE_TIMEOUT_SEC = 3.0        # 单次 /system_stats 探测超时
START_READY_TIMEOUT_SEC = 180.0  # start 阻塞等待就绪上限（重型插件包冷启动远超 60s）
STOP_GRACEFUL_SEC = 10.0       # 优雅终止等待
STOP_FORCE_WAIT_SEC = 5.0      # 强杀后确认等待

# --- 配置 ---
SCHEMA_VERSION = 1

# --- 镜像三件套默认值 ---
DEFAULT_HF_MIRROR = "https://hf-mirror.com"
DEFAULT_GITHUB_PROXY = "https://gh-proxy.com/"
PIP_MIRRORS = {
    "tuna": "https://pypi.tuna.tsinghua.edu.cn/simple",
    "aliyun": "https://mirrors.aliyun.com/pypi/simple/",
    "huawei": "https://repo.huaweicloud.com/repository/pypi/simple",
}

# --- 运行时目录定位 ---
# 优先级：环境变量 > 包所在目录（便携式：启动台放哪，配置在哪）


def default_config_dir() -> Path:
    env = os.environ.get("WANDAO_LAUNCHPAD_HOME")
    if env:
        return Path(env)
    # 冻结模式（PyInstaller）：配置跟 exe 走（便携）；源码模式：跟项目根走
    import sys
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "launchpad"
    return Path(__file__).resolve().parent.parent / "launchpad"


def config_file_path(config_dir: Path | None = None) -> Path:
    return (config_dir or default_config_dir()) / "config.json"


def pidfile_path(config_dir: Path | None = None) -> Path:
    return (config_dir or default_config_dir()) / "comfyui.pid"


def launcher_log_path(config_dir: Path | None = None) -> Path:
    return (config_dir or default_config_dir()) / "logs" / "launchpad.log"

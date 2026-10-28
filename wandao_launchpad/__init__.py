"""万道启动台（WandaoLaunchpad）—— ComfyUI 启动器。

设计铁律（继承自对标分析，改动前先读 AGENTS.md）：
1. 只做编排器，不分叉 ComfyUI 内核。
2. core 层（本包除 gui/ 外）禁止 import PyQt5——有测试守着。
3. 进程生命周期只有一个 owner（process_manager），杀进程永远定点、单次、验尸。
4. 同一逻辑只留一份实现（pidfile/配置/版本解析各一份）。
5. 禁止裸 ``except: pass``——吞异常必须留日志。
"""

__version__ = "0.11.1"

from .constants import APP_NAME  # noqa: E402,F401  (constants 无回向依赖，安全)

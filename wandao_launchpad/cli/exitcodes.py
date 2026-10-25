"""CLI 退出码契约——集中定义，跨版本稳定。

外部脚本按这张表分支，请勿随意改值（改语义 = 破坏契约 = 大事故）。
"""

EXIT_OK = 0               # 成功
EXIT_ERROR = 1            # 通用错误（配置缺失、路径非法、IO、超时）
EXIT_ALREADY_RUNNING = 2  # start：已有实例在跑，拒绝重复启动
EXIT_NOT_RUNNING = 3      # status：未运行

EXIT_NAMES = {
    EXIT_OK: "ok",
    EXIT_ERROR: "error",
    EXIT_ALREADY_RUNNING: "already_running",
    EXIT_NOT_RUNNING: "not_running",
}

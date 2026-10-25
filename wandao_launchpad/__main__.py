"""入口：无参数 → GUI；带子命令 → headless CLI（复用同一套核心层）。"""

from __future__ import annotations

import sys


def _is_cli_invocation(argv: list[str]) -> bool:
    cli_verbs = {"start", "stop", "status", "restart", "info", "logs", "plugins",
                 "kernel", "models", "support", "doctor", "archive", "help",
                 "-h", "--help", "--json", "-v", "--version"}
    return bool(argv) and argv[0] in cli_verbs


def main() -> int:
    argv = sys.argv[1:]
    if _is_cli_invocation(argv):
        from .logging_setup import setup_logging
        setup_logging()
        from .cli.main import main as cli_main
        return cli_main(argv)
    # 无参数（或显式 gui）→ GUI
    if argv and argv[0] == "gui":
        argv = argv[1:]
    from .logging_setup import setup_logging
    setup_logging()
    from .gui.app import run_gui
    return run_gui(argv)


if __name__ == "__main__":
    raise SystemExit(main())

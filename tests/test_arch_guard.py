"""架构守卫——用测试锁住分层铁律（Mie 的教训制度化）。

1. core 层（wandao_launchpad 除 gui/ 外）禁止 import PyQt5。
2. 全项目禁止裸 ``except: pass``（吞异常必须留日志或显式忽略注释）。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "wandao_launchpad"


def _py_files():
    return [p for p in ROOT.rglob("*.py") if "__pycache__" not in p.parts]


def test_core_never_imports_pyqt():
    offenders = []
    for path in _py_files():
        if "gui" in path.parts:
            continue
        src = path.read_text(encoding="utf-8")
        if re.search(r"^\s*(import|from)\s+PyQt5", src, re.M):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"core 层混入 PyQt5 依赖: {offenders}"


def test_no_bare_except_pass():
    """裸 except: pass / except Exception: pass 一律不许（先 logger 后吞才行）。"""
    offenders = []
    for path in _py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            offenders.append(f"{path.relative_to(ROOT)}: 语法错误")
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                body = node.body
                only_pass = len(body) == 1 and isinstance(body[0], ast.Pass)
                if only_pass:
                    offenders.append(
                        f"{path.relative_to(ROOT)}:{node.lineno} 裸 except+pass")
    assert offenders == [], f"发现裸吞异常: {offenders}"


def test_no_qt_in_process_manager_import_graph():
    # 双保险：进程管理器模块编译产物里不该出现 Qt 字样
    src = (ROOT / "process_manager.py").read_text(encoding="utf-8")
    assert "PyQt" not in src and "QtWidgets" not in src

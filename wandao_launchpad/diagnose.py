"""启动失败智能诊断——把日志尾部翻译成"出了什么事 + 建议做什么"。

纯函数核心：diagnose(log_text) → 命中的已知模式列表。不猜、不联网，
只认日志里实际出现的字样；没命中就如实说"未见已知模式"。
"""
from __future__ import annotations

import re

# (id, 标题, 匹配正则[可含1个捕获组], 建议动作, 级别)
PATTERNS: list[tuple[str, str, str, str, str]] = [
    ("cuda_oom", "显存不足（CUDA OOM）",
     r"CUDA out of memory|OutOfMemoryError",
     "关闭其他占显存的程序；启动页换「大模型低显存」预设；或换更小的模型/关掉高清修复类节点",
     "error"),
    ("module_missing", "缺少 Python 模块",
     r"ModuleNotFoundError: No module named '([^']+)'",
     "插件依赖没装齐：在插件页重装该插件（会自动装依赖），或手动 pip install 缺的模块",
     "error"),
    ("port_busy", "端口被占用",
     r"address already in use|Only one usage of each socket|\[Errno 10048\]",
     "换个端口（启动页），或停掉占用当前端口的实例（status 看 external）",
     "error"),
    ("frontend_mismatch", "前端包版本不匹配",
     r"frontend[_ ]package.*(?:not compatible|required|outdated)|"
     r"comfyui[-_]frontend.*(?:mismatch|too old)|Failed to import the ComfyUI frontend",
     "内核页更新时勾选「同步依赖库」，或手动升级 comfyui-frontend-package",
     "error"),
    ("import_failed", "插件加载失败",
     r"IMPORT FAILED\s*(?:[:：]?\s*(\S+))?",
     "在插件页禁用报错的插件，重启验证；确认该插件依赖已装",
     "warn"),
    ("cuda_kernel", "Torch 与显卡不匹配",
     r"no kernel image is available for execution on the device",
     "torch 版本与显卡架构/驱动不匹配——确认最近没人动过 torch（启动台自身不会碰它）",
     "error"),
    ("driver_old", "显卡驱动过旧",
     r"NVIDIA driver is too old|update your NVIDIA (?:graphics )?driver",
     "升级显卡驱动到新版",
     "error"),
    ("dll_load", "DLL 加载失败",
     r"OSError: \[(?:WinError 126|WinError 1114)\]|DLL load failed",
     "通常是 VC 运行库或 CUDA 组件损坏：装 VC Redist；最近装过新包的话先卸载试回",
     "error"),
    ("traceback", "出现异常堆栈",
     r"Traceback \(most recent call last\)",
     "上面各项若都没命中，看日志尾部最后几行的异常名（支持包里有全文）",
     "warn"),
]

_COMPILED = [(pid, title, re.compile(pat, re.I), advice, level)
             for pid, title, pat, advice, level in PATTERNS]


def diagnose(log_text: str) -> list[dict]:
    """返回命中的已知模式（同 id 去重，保持日志中的出现顺序）。"""
    found: list[dict] = []
    seen: set[str] = set()
    for pid, title, pat, advice, level in _COMPILED:
        m = pat.search(log_text)
        if not m or pid in seen:
            continue
        seen.add(pid)
        detail = m.group(1) if (m.groups() and m.group(1)) else ""
        found.append({"id": pid, "title": title,
                      "detail": detail, "advice": advice, "level": level})
    return found


def last_error_lines(log_text: str, n: int = 8) -> list[str]:
    """取日志尾部最后 n 行（供展示）。"""
    lines = [l.rstrip() for l in log_text.splitlines() if l.strip()]
    return lines[-n:]


def format_diagnosis(items: list[dict], log_text: str = "") -> str:
    """人话排版（GUI 弹窗/CLI 文案共用）。"""
    if not items:
        tail = last_error_lines(log_text)
        body = ("\n".join(tail[-5:]) if tail else "（日志无内容）")
        return "未见已知错误模式。\n日志尾部：\n" + body
    parts = []
    for it in items:
        line = f"【{it['title']}】"
        if it.get("detail"):
            line += f" {it['detail']}"
        parts.append(line + "\n  → " + it["advice"])
    return "\n\n".join(parts)

"""pip 子进程封装——全项目唯一的 pip 操作入口（单一实现铁律）。

安全红线：torch/torchvision/torchaudio/triton 是 CUDA 耦合件（版本与显卡驱动
精确配套，本机 torch cu12x 是手工调过的），**永远不允许 pip 动它们**——
所有依赖安装一律先过 freeze 过滤。
"""
from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path

from .proc import run_hidden

logger = logging.getLogger(__name__)

# CUDA 耦合件冻结名单（小写、规范化比较）
FROZEN_PKGS = {"torch", "torchvision", "torchaudio", "triton"}

PIP_TIMEOUT = 1800.0  # 依赖安装可能很慢（下载 + 编译轮子），给足上限

_REQ_NAME_RE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def _norm(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def is_frozen_line(line: str) -> bool:
    """该 requirements 行是否命中冻结名单（注释/空行/选项行不命中）。"""
    s = line.strip()
    if not s or s.startswith("#") or s.startswith("-"):
        return False
    m = _REQ_NAME_RE.match(s)
    return bool(m and _norm(m.group(1)) in FROZEN_PKGS)


def filter_requirements(text: str) -> tuple[str, list[str]]:
    """过滤冻结包，返回 (保留的 requirements 文本, 被剔除的行)。"""
    kept: list[str] = []
    dropped: list[str] = []
    for line in text.splitlines():
        if is_frozen_line(line):
            dropped.append(line.strip())
        else:
            kept.append(line)
    return "\n".join(kept), dropped


def build_install_cmd(python_exe: str, req_file: Path, index_url: str | None,
                      upgrade: bool = False) -> list[str]:
    argv = [python_exe, "-m", "pip", "install",
            "-r", str(req_file), "--no-input"]
    if upgrade:
        argv += ["--upgrade", "--upgrade-strategy", "only-if-needed"]
    if index_url:
        argv += ["-i", index_url]
    return argv


def _run_pip(argv: list[str], timeout: float) -> tuple[bool, str]:
    try:
        rc, out, err = run_hidden(argv, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 —— 子进程层异常（超时/OS）如实上报
        logger.warning("pip 执行失败: %s", exc, exc_info=True)
        return False, str(exc)
    log = (out + ("\n" + err if err else "")).strip()
    return rc == 0, log[-3000:]  # 尾部 3KB 足够定位


def ensure_requirements(plugin_dir: Path, python_exe: str,
                        index_url: str | None = None,
                        timeout: float = PIP_TIMEOUT) -> dict:
    """装插件目录的 requirements.txt（缺文件=ran False；只装缺失，不升级既有）。"""
    req = Path(plugin_dir) / "requirements.txt"
    if not req.exists():
        return {"ran": False, "ok": None, "log": "", "reason": "无 requirements.txt"}
    argv = build_install_cmd(python_exe, req, index_url, upgrade=False)
    ok, log = _run_pip(argv, timeout)
    return {"ran": True, "ok": ok, "log": log, "reason": None if ok else "pip 非零退出"}


def sync_comfy_requirements(comfy_root: Path, python_exe: str,
                            index_url: str | None = None,
                            timeout: float = PIP_TIMEOUT) -> dict:
    """内核更新后的依赖同步：upgrade only-if-needed + 冻结过滤（保 CUDA 栈）。"""
    req = Path(comfy_root) / "requirements.txt"
    if not req.exists():
        return {"ran": False, "ok": None, "log": "", "reason": "内核无 requirements.txt",
                "dropped": []}
    text = req.read_text(encoding="utf-8", errors="replace")
    filtered, dropped = filter_requirements(text)
    fd, tmp_name = tempfile.mkstemp(suffix="-requirements.txt")
    tmp = Path(tmp_name)
    try:
        tmp.write_text(filtered, encoding="utf-8")
        argv = build_install_cmd(python_exe, tmp, index_url, upgrade=True)
        ok, log = _run_pip(argv, timeout)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            logger.debug("临时 requirements 清理失败", exc_info=True)
    reason = None if ok else "pip 非零退出（冻结包已剔除，CUDA 栈未受影响）"
    return {"ran": True, "ok": ok, "log": log, "reason": reason, "dropped": dropped}

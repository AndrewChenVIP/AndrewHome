"""内核版本管理——ComfyUI 根仓库的 git 操作。

教训对策：
- 更新只做 --ff-only + 运行中拒绝（端口真相）+ 脏树拒绝——绝不强推现场。
- "仅稳定版"按 vX.Y.Z 语义标签挑（排除 rc/beta/dev 后缀）。
- 历史只读（git log），checkout 要求干净树且服务未运行。
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from .proc import git
from .probe import probe

logger = logging.getLogger(__name__)

_STABLE_TAG = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_GIT_TIMEOUT = 120.0


@dataclass
class KernelInfo:
    comfyui_version: str       # comfyui_version.py 的 __version__（官方语义版本）
    commit: str                # HEAD 短哈希
    commit_date: str
    commit_subject: str
    dirty: bool


class KernelService:
    def __init__(self, comfyui_root: Path, base_url: str | None = None):
        """comfyui_root: 含 .git 的内核仓库（如 E:/ComfyUI_Mie_V9.0/ComfyUI）。

        base_url: ComfyUI 服务地址（运行中拒绝写操作）；None = 不做运行检查。
        """
        self.root = Path(comfyui_root)
        self.base_url = base_url

    # ---------- 基础 ----------

    def _running(self) -> bool:
        return self.base_url is not None and probe(self.base_url)

    def _assert_writable(self) -> None:
        if self._running():
            raise RuntimeError("ComfyUI 正在运行，拒绝内核写操作（先停止再试）")
        rc, status, _ = git(["status", "--porcelain"], cwd=str(self.root),
                            timeout=_GIT_TIMEOUT)
        if rc == 0 and status.strip():
            raise RuntimeError(f"内核工作树脏（{len(status.splitlines())} 处改动），拒绝操作")

    # ---------- 查询 ----------

    def info(self) -> KernelInfo:
        version = ""
        vf = self.root / "comfyui_version.py"
        if vf.exists():
            m = re.search(r'__version__\s*=\s*"([^"]+)"', vf.read_text(encoding="utf-8-sig"))
            if m:
                version = m.group(1)
        rc, out, _ = git(["log", "-1", "--format=%h|%ci|%s"], cwd=str(self.root),
                         timeout=_GIT_TIMEOUT)
        commit, date, subject = (out.split("|", 2) + ["", ""])[:3] if rc == 0 and out else ("", "", "")
        rc2, status, _ = git(["status", "--porcelain"], cwd=str(self.root),
                             timeout=_GIT_TIMEOUT)
        return KernelInfo(comfyui_version=version, commit=commit,
                          commit_date=date.strip(), commit_subject=subject.strip(),
                          dirty=bool(rc2 == 0 and status.strip()))

    def log(self, count: int = 50, skip: int = 0) -> list[dict]:
        rc, out, err = git(
            ["log", f"--skip={skip}", f"-{count}",
             "--format=%h|%ci|%an|%s"],
            cwd=str(self.root), timeout=_GIT_TIMEOUT)
        if rc != 0:
            raise RuntimeError(f"git log 失败: {err[:200]}")
        rows = []
        for line in out.splitlines():
            parts = (line.split("|", 3) + ["", "", "", ""])[:4]
            rows.append({"commit": parts[0], "date": parts[1],
                         "author": parts[2], "subject": parts[3]})
        return rows

    # ---------- 更新 ----------

    def _tags(self) -> list[str]:
        rc, out, _ = git(["tag", "--list"], cwd=str(self.root), timeout=_GIT_TIMEOUT)
        if rc != 0:
            return []
        return [t for t in out.splitlines() if _STABLE_TAG.match(t.strip())]

    def latest_stable_tag(self) -> str | None:
        def key(tag: str) -> tuple:
            m = _STABLE_TAG.match(tag)
            return tuple(int(x) for x in m.groups())  # type: ignore[union-attr]
        tags = self._tags()
        return max(tags, key=key) if tags else None

    def update(self, dry_run: bool = False, stable_only: bool = False) -> dict:
        """fetch + ff-only 更新。返回 updated/from/to/log；已是最新时 updated=False。"""
        rc, out, err = git(["fetch", "origin", "--tags"], cwd=str(self.root),
                           timeout=600.0)
        if rc != 0:
            raise RuntimeError(f"git fetch 失败: {err[:200]}")

        before = self.info()
        if stable_only:
            tag = self.latest_stable_tag()
            if not tag:
                raise RuntimeError("找不到稳定版标签（vX.Y.Z 语义）")
            rc, out, err = git(["rev-parse", tag], cwd=str(self.root), timeout=_GIT_TIMEOUT)
            if rc != 0:
                raise RuntimeError(f"解析标签失败: {tag}")
            target, target_desc = out.strip(), tag
        else:
            rc, out, err = git(["rev-parse", "origin/main"], cwd=str(self.root),
                               timeout=_GIT_TIMEOUT)
            if rc != 0:
                raise RuntimeError("解析 origin/main 失败（分支名非 main？）")
            target, target_desc = out.strip(), "origin/main"

        head = before.commit
        if head and head in target:  # 短哈希在长哈希里 = 已在同一提交
            return {"updated": False, "from": head, "to": target_desc, "log": "已是最新"}

        plan = {"updated": True, "from": head, "to": target_desc}
        if dry_run:
            plan["log"] = f"将更新到 {target_desc}"
            return plan

        self._assert_writable()
        if stable_only:
            rc, out, err = git(["checkout", target_desc], cwd=str(self.root),
                               timeout=_GIT_TIMEOUT)
        else:
            rc, out, err = git(["merge", "--ff-only", "origin/main"],
                               cwd=str(self.root), timeout=_GIT_TIMEOUT)
        if rc != 0:
            raise RuntimeError(f"更新失败: {err[:300]}")
        after = self.info()
        plan["log"] = out.strip()[:300]
        plan["to"] = f"{after.commit} ({after.comfyui_version})"
        return plan

    def checkout(self, ref: str) -> str:
        self._assert_writable()
        rc, out, err = git(["checkout", ref], cwd=str(self.root), timeout=_GIT_TIMEOUT)
        if rc != 0:
            raise RuntimeError(f"checkout 失败: {err[:200]}")
        return self.info().commit

"""插件管理——custom_nodes 的扫描/启停/并行检查更新/更新。

教训对策（Mie 插件检查更新串行分钟级）：
- check_updates 用 ThreadPoolExecutor 并行（默认 8 worker）。
- list 是纯目录扫描（快路径），git 信息只在需要时取。
- 启停沿用 ComfyUI-Manager 的 `.disabled` 目录后缀约定。
- 更新只对"干净树的 git 插件"做 pull --ff-only；脏树跳过并报原因——不 stash
  用户未提交的改动（比 Mie 的 stash 方案保守：宁可不更新，不动用户现场）。
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path

from .proc import git

logger = logging.getLogger(__name__)

DISABLED_SUFFIX = ".disabled"
CHECK_WORKERS = 8
GIT_TIMEOUT = 30.0


@dataclass
class PluginInfo:
    name: str            # 刻掉 .disabled 的纯名（后续操作传 dir_name）
    dir_name: str        # 实际目录名（可能带 .disabled）
    is_git: bool
    enabled: bool
    outdated: bool | None = None   # None = 未检查；list 不填
    local_head: str = ""
    remote_head: str = ""


class PluginService:
    def __init__(self, custom_nodes_dir: Path):
        self.dir = Path(custom_nodes_dir)

    # ---------- 扫描（纯目录，快） ----------

    def list(self) -> list[PluginInfo]:
        result: list[PluginInfo] = []
        if not self.dir.is_dir():
            return result
        for child in sorted(self.dir.iterdir()):
            if not child.is_dir() or child.name.startswith((".", "__")):
                continue
            if child.name == "__pycache__":
                continue
            disabled = child.name.endswith(DISABLED_SUFFIX)
            result.append(PluginInfo(
                name=child.name[:-len(DISABLED_SUFFIX)] if disabled else child.name,
                dir_name=child.name,
                is_git=(child / ".git").exists(),
                enabled=not disabled,
            ))
        return result

    def _find(self, dir_name: str) -> Path:
        p = self.dir / dir_name
        if not p.is_dir():
            raise FileNotFoundError(f"插件不存在: {dir_name}")
        return p

    # ---------- 启停（.disabled 后缀约定） ----------

    def set_enabled(self, dir_name: str, enabled: bool) -> PluginInfo:
        p = self._find(dir_name)
        currently = not p.name.endswith(DISABLED_SUFFIX)
        if enabled == currently:
            return self._info_of(p)
        if enabled:
            # 启用 → 去掉 .disabled 后缀（防御：名长不足以剥时原样保留）
            base = p.name[:-len(DISABLED_SUFFIX)]
            new_name = base or p.name
        else:
            # 禁用 → 加 .disabled 后缀
            new_name = p.name + DISABLED_SUFFIX
        target = p.with_name(new_name)
        p.rename(target)
        return self._info_of(target)

    def _info_of(self, p: Path) -> PluginInfo:
        disabled = p.name.endswith(DISABLED_SUFFIX)
        return PluginInfo(
            name=p.name[:-len(DISABLED_SUFFIX)] if disabled else p.name,
            dir_name=p.name, is_git=(p / ".git").exists(), enabled=not disabled)

    def uninstall(self, dir_name: str) -> None:
        """卸载 = 删目录。调用方负责确认（CLI/GUI 必须先弹确认）。"""
        import shutil
        p = self._find(dir_name)
        shutil.rmtree(p)

    # ---------- 检查更新（并行） ----------

    @staticmethod
    def _check_one(path: Path) -> tuple[str, bool | None, str, str, str]:
        """返回 (dir_name, outdated|None, local, remote, error)。"""
        rc, local, err = git(["rev-parse", "HEAD"], cwd=str(path), timeout=GIT_TIMEOUT)
        if rc != 0:
            return path.name, None, "", "", f"rev-parse 失败: {err[:120]}"
        rc, remote, err = git(["ls-remote", "origin", "HEAD"], cwd=str(path),
                              timeout=GIT_TIMEOUT)
        if rc != 0:
            return path.name, None, local, "", f"ls-remote 失败: {err[:120]}"
        remote = remote.split("\t", 1)[0] if "\t" in remote else remote.split()[0] if remote else ""
        if not remote:
            return path.name, None, local, "", "远端无 HEAD"
        return path.name, local != remote, local[:12], remote[:12], ""

    def check_updates(self) -> list[dict]:
        """并行检查全部 git 插件。返回逐项结果（含失败原因），不抛异常。"""
        git_plugins = [self.dir / p.dir_name for p in self.list() if p.is_git and p.enabled]
        results: dict[str, dict] = {}
        if not git_plugins:
            return []
        with ThreadPoolExecutor(max_workers=CHECK_WORKERS) as pool:
            futures = {pool.submit(self._check_one, p): p for p in git_plugins}
            for fut in as_completed(futures):
                path = futures[fut]
                try:
                    dir_name, outdated, local, remote, error = fut.result()
                except Exception as exc:  # noqa: BLE001 —— 单插件失败不拖垮整批
                    logger.warning("插件检查异常 %s", path.name, exc_info=True)
                    dir_name, outdated, local, remote, error = (
                        path.name, None, "", "", str(exc))
                results[dir_name] = {
                    "dir_name": dir_name, "outdated": outdated,
                    "local": local, "remote": remote, "error": error or None,
                }
        return [results[k] for k in sorted(results)]

    # ---------- 更新 ----------

    def update_one(self, dir_name: str) -> dict:
        p = self._find(dir_name)
        if not (p / ".git").exists():
            return {"dir_name": dir_name, "ok": False, "skipped": True,
                    "detail": "非 git 插件"}
        rc, status, _ = git(["status", "--porcelain"], cwd=str(p), timeout=GIT_TIMEOUT)
        if rc != 0:
            return {"dir_name": dir_name, "ok": False, "skipped": True,
                    "detail": "git status 失败"}
        if status.strip():
            return {"dir_name": dir_name, "ok": False, "skipped": True,
                    "detail": f"工作树脏（{len(status.splitlines())} 处改动），跳过不动现场"}
        rc, out, err = git(["pull", "--ff-only"], cwd=str(p), timeout=300.0)
        if rc != 0:
            return {"dir_name": dir_name, "ok": False, "skipped": False,
                    "detail": f"pull 失败: {err[:200]}"}
        return {"dir_name": dir_name, "ok": True, "skipped": False, "detail": out.strip()[:300]}

    def update_all(self, only: list[str] | None = None) -> list[dict]:
        targets = only or [p.dir_name for p in self.list() if p.is_git and p.enabled]
        return [self.update_one(d) for d in sorted(targets)]

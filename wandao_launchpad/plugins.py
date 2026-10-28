"""插件管理——custom_nodes 的扫描/启停/并行检查更新/更新。

教训对策（Mie 插件检查更新串行分钟级）：
- check_updates 用 ThreadPoolExecutor 并行（默认 8 worker）。
- list 是纯目录扫描（快路径），git 信息只在需要时取。
- 启停沿用 ComfyUI-Manager 的 `.disabled` 目录后缀约定。
- 更新只对"干净树的 git 插件"做 pull --ff-only；脏树跳过并报原因——不 stash
  用户未提交的改动（比 Mie 的 stash 方案保守：宁可不更新，不动用户现场）。
"""
from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from .proc import git

logger = logging.getLogger(__name__)

DISABLED_SUFFIX = ".disabled"
CHECK_WORKERS = 8
GIT_TIMEOUT = 30.0

# ComfyUI-Manager 官方插件清单（搜索/按名安装的解析源）
NODE_LIST_URL = ("https://raw.githubusercontent.com/ltdrdata/"
                 "ComfyUI-Manager/main/custom-node-list.json")
# 第二清单源：jsDelivr CDN 镜像（免代理可达），直连/代理全挂时的网络侧兜底
NODE_LIST_CDN_URL = ("https://cdn.jsdelivr.net/gh/ltdrdata/"
                     "ComfyUI-Manager@main/custom-node-list.json")
NODE_LIST_TTL_SEC = 3600.0


@dataclass
class NodeListEntry:
    name: str
    description: str
    reference: str          # 主页/仓库地址
    install_url: str        # 可 clone 的 git 地址
    author: str


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
    def __init__(self, custom_nodes_dir: Path, cache_dir: Path | None = None,
                 github_proxy: str = ""):
        self.dir = Path(custom_nodes_dir)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.github_proxy = (github_proxy or "").strip()

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
                    "detail": f"pull 失败: {err[:200]}", "changed": False}
        changed = "up to date" not in out.lower()
        return {"dir_name": dir_name, "ok": True, "skipped": False,
                "detail": out.strip()[:300], "changed": changed}

    def update_all(self, only: list[str] | None = None) -> list[dict]:
        targets = only or [p.dir_name for p in self.list() if p.is_git and p.enabled]
        return [self.update_one(d) for d in sorted(targets)]

    # ---------- 搜索与安装 ----------

    def _node_list_cache_path(self) -> Path | None:
        return self.cache_dir / "node_list_cache.json" if self.cache_dir else None

    def _cache_entries(self, cache: Path | None, *,
                       ignore_ttl: bool = False) -> list[NodeListEntry] | None:
        """读缓存清单；过期/损坏返回 None（ignore_ttl=True 供全通道失败时容灾）。"""
        if not (cache and cache.exists()):
            return None
        try:
            raw = json.loads(cache.read_text(encoding="utf-8-sig"))
            if not ignore_ttl and \
                    time.time() - float(raw.get("fetched_at", 0)) >= NODE_LIST_TTL_SEC:
                return None
            return [NodeListEntry(**e) for e in raw.get("nodes", [])]
        except (OSError, ValueError, TypeError):
            logger.debug("节点清单缓存读取失败（ignore_ttl=%s）", ignore_ttl,
                         exc_info=True)
            return None

    @staticmethod
    def _parse_node_list(data: object) -> list[NodeListEntry]:
        """官方清单 → 条目。顶层兼容 dict（现行 custom_nodes 包裹）与 list（旧形态）；
        条目安装地址兼容 installed_ver/aux_id（旧 node_db 形态）与 files（现行真身）。"""
        items: object = []
        if isinstance(data, dict):
            items = data.get("custom_nodes") or []
        elif isinstance(data, list):
            items = data
        if not isinstance(items, list):
            items = []
        entries: list[NodeListEntry] = []
        for item in items:
            try:
                name = str(item.get("title", "") or item.get("name", "") or "")
                ref = str(item.get("reference", "") or "")
                install = ""
                for sec in item.get("installed_ver", []) or item.get("aux_id", []) or []:
                    if isinstance(sec, dict) and str(sec.get("type", "")) == "git-clone":
                        install = str(sec.get("id", ""))
                        break
                if not install:
                    for f in item.get("files", []) or []:
                        f = str(f)
                        if f.startswith(("http://", "https://")):
                            install = f
                            break
                if not install and ref:
                    install = ref
                author = str(item.get("author", "") or "")
                if not author:
                    m = re.search(r"github\.com/([^/]+)/", ref + "/")
                    if m:
                        author = m.group(1)
                if name and install:
                    entries.append(NodeListEntry(
                        name=name[:120],
                        description=str(item.get("description", ""))[:300],
                        reference=ref, install_url=install, author=author))
            except (AttributeError, TypeError):
                logger.debug("清单条目解析跳过", exc_info=True)
        return entries

    def _load_node_list(self, force: bool = False) -> list[NodeListEntry]:
        """官方 custom-node-list.json（直连→代理→CDN 三通道；缓存 1h；
        全通道挂时降级用过期缓存——清单只影响发现，安装仍走 git HEAD；
        拿到但解析为空视同通道失败，绝不把空清单写进缓存。"""
        import urllib.request

        cache = self._node_list_cache_path()
        if not force:
            fresh = self._cache_entries(cache)
            if fresh is not None:
                return fresh

        urls = [NODE_LIST_URL]
        if self.github_proxy:
            urls.append(self.github_proxy.rstrip("/") + "/" + NODE_LIST_URL)
        urls.append(NODE_LIST_CDN_URL)
        entries: list[NodeListEntry] = []
        last_err = ""
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "WandaoLaunchpad"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                parsed = self._parse_node_list(data)
            except (OSError, ValueError) as exc:
                last_err = str(exc)
                logger.debug("节点清单获取失败 %s: %s", url, exc)
                continue
            if parsed:
                entries = parsed
                break
            logger.debug("清单通道返回空/不可解析，试下一通道: %s", url)
        if not entries:
            stale = self._cache_entries(cache, ignore_ttl=True)
            if stale:
                logger.warning("插件清单全部通道失败，降级用本地缓存（可能过期）")
                return stale
            raise RuntimeError(f"插件清单获取失败（直连/代理/CDN 全部失败）: {last_err[:200]}")
        if cache:
            try:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(
                    {"fetched_at": time.time(),
                     "nodes": [e.__dict__ for e in entries]}, ensure_ascii=False),
                    encoding="utf-8")
            except OSError:
                logger.debug("节点清单缓存写入失败", exc_info=True)
        return entries

    def search(self, query: str, limit: int = 30) -> list[NodeListEntry]:
        q = query.strip().lower()
        if not q:
            return []
        scored: list[tuple[int, NodeListEntry]] = []
        for e in self._load_node_list():
            hay = f"{e.name} {e.description} {e.author}".lower()
            if q in e.name.lower():
                scored.append((0, e))
            elif q in hay:
                scored.append((1, e))
        scored.sort(key=lambda pair: (pair[0], pair[1].name))
        return [e for _, e in scored[:limit]]

    def _proxied(self, url: str) -> str:
        if self.github_proxy and "github.com" in url:
            return self.github_proxy.rstrip("/") + "/" + url
        return url

    def install(self, target: str) -> PluginInfo:
        """target = git URL / 本地仓库路径 / 插件名（按官方清单解析）。"""
        url = target.strip()
        looks_like_location = (url.startswith(("http://", "https://", "file://"))
                               or "\\" in url or "/" in url or url.endswith(".git"))
        if not looks_like_location:
            matches = [e for e in self._load_node_list()
                       if e.name.lower() == url.lower()]
            if not matches:
                matches = [e for e in self.search(url, limit=1)]
            if not matches:
                raise RuntimeError(f"清单中找不到插件: {target}（也可直接给 git URL）")
            url = matches[0].install_url
        raw = url.rstrip("/")
        if raw.endswith(".git"):
            raw = raw[:-len(".git")]
        dir_name = raw.replace("\\", "/").rsplit("/", 1)[-1]
        if not dir_name:
            raise RuntimeError(f"无法从 URL 推导目录名: {url}")
        dest = self.dir / dir_name
        if dest.exists():
            raise FileExistsError(f"已存在同名目录: {dir_name}")
        rc, out, err = git(["clone", "--depth", "1", self._proxied(url), str(dest)],
                           timeout=600.0)
        if rc != 0:
            # 失败清残骸，不留半拉子目录
            import shutil
            try:
                shutil.rmtree(dest, ignore_errors=True)
            except OSError:
                logger.debug("克隆失败清理残留", exc_info=True)
            raise RuntimeError(f"clone 失败: {err[:200]}")
        return self._info_of(dest)

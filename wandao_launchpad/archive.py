"""出图归档——把 ComfyUI output 的新作品按"只增不删"拷进 NAS 作品库。

语义（与 WandaoOS 归档红线一致）：
- 只新增，永不删除/覆盖 NAS 已有文件；
- 同名同大小 → 视为已归档，跳过；
- 同名不同大小 → 改名续位（name_2 / name_3…），不动原文件；
- 落点自动按日期分夹（target/YYYY-MM-DD/），批次可追溯；
- 空间预检 + NAS 可达预检（离线时整体失败并给明确原因，不产生半批状态）。

默认只处理图像（视频另落 点，待老板定夺再开）。
"""
from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
DEFAULT_ARCHIVE_TARGET = r"\\100.108.142.97\Accumulation\WandaoOS\06AIGC作品库\图像"
LIST_LIMIT = 500


def output_dir_of(comfyui_root: Path) -> Path:
    return Path(comfyui_root) / "ComfyUI" / "output"


def list_recent_outputs(output_dir: Path, limit: int = LIST_LIMIT,
                        exts: set[str] | None = None) -> list[dict]:
    """按修改时间倒序列出输出目录下的图像（含子目录）。"""
    exts = exts or IMAGE_EXTS
    root = Path(output_dir)
    if not root.is_dir():
        return []
    items: list[dict] = []
    for p in root.rglob("*"):
        try:
            if not p.is_file() or p.suffix.lower() not in exts:
                continue
            st = p.stat()
            items.append({
                "path": str(p),
                "rel": str(p.relative_to(root)),
                "size": st.st_size,
                "mtime": st.st_mtime,
            })
        except OSError:
            logger.debug("输出文件枚举跳过: %s", p, exc_info=True)
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items[:limit]


def _dedup_target(dest: Path) -> Path:
    """同名不同大小 → _2/_3 续位（只增不删：绝不覆盖）。"""
    if not dest.exists():
        return dest
    stem, suffix = dest.stem, dest.suffix
    n = 2
    while True:
        cand = dest.with_name(f"{stem}_{n}{suffix}")
        if not cand.exists():
            return cand
        n += 1


def archive_files(files: list[dict], target: str | Path,
                  date_subfolder: bool = True) -> dict:
    """把选中文件拷进落点。返回 {copied, skipped, renamed, failed, target}。

    前置预检：落点可达（建日期夹即验证）+ 空间足够；预检失败整体失败，
    不产生拷了一半的状态（单文件失败则逐项记 failed，其余继续）。
    """
    target = Path(target)
    day = datetime.now().strftime("%Y-%m-%d")
    dest_dir = target / day if date_subfolder else target
    result = {"copied": [], "skipped": [], "renamed": [], "failed": [],
              "target": str(dest_dir)}

    total = sum(f.get("size", 0) for f in files)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        for f in files:
            result["failed"].append({**f, "reason": f"落点不可达: {exc}"})
        return result
    if total:
        try:
            free = shutil.disk_usage(str(dest_dir)).free
            if free < total:
                for f in files:
                    result["failed"].append({
                        **f,
                        "reason": f"落点空间不足（需 {total/1024**2:.0f}MB，剩 {free/1024**3:.1f}GB）",
                    })
                return result
        except OSError:
            logger.debug("落点空间检查失败（继续逐项尝试）", exc_info=True)

    for f in files:
        src = Path(f["path"])
        dest = dest_dir / src.name
        try:
            if dest.exists():
                if dest.stat().st_size == src.stat().st_size:
                    result["skipped"].append({**f, "reason": "同名同大小，已归档过"})
                    continue
                dest = _dedup_target(dest)
                result["renamed"].append({**f, "dest": str(dest)})
            shutil.copy2(src, dest)
            result["copied"].append({**f, "dest": str(dest)})
        except OSError as exc:
            logger.warning("归档单文件失败: %s", src, exc_info=True)
            result["failed"].append({**f, "reason": str(exc)})
    return result

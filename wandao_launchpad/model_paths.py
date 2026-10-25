"""外置模型库——extra_model_paths.yaml 的生成与管理。

教训对策（Mie 直接编辑 yaml、并发写非原子、手拼 yaml 遇特殊路径就坏）：
- **sidecar 是唯一真源**：库列表存启动台自己的 model_libs.json（原子写），
  extra_model_paths.yaml 是**渲染产物**（apply 时生成，旧文件先备份）。
- yaml 用 PyYAML 安全渲染（allow_unicode），路径含 #/空格/中文都不会坏。
- ComfyUI 侧已有的 yaml 可一次性 import 进 sidecar（只增语义，不动原文件）。
"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path

import yaml

from .constants import SCHEMA_VERSION  # noqa: F401  (sidecar 语义对齐)

logger = logging.getLogger(__name__)

# ComfyUI 认识的模型目录类型（extra_model_paths.yaml 的合法键）
KNOWN_TYPES = (
    "checkpoints", "clip", "clip_vision", "configs", "controlnet", "diffusers",
    "diffusion_models", "embeddings", "gligen", "hypernetworks", "loras",
    "photomaker", "sams", "sam_templates", "text_encoders", "t5_encoder",
    "t5_tokenizers", "ultralytics", "ultralytics_bbox", "ultralytics_segm",
    "vae", "vae_approx", "upscale_models", "latent_upscale_models",
    "animatediff_models", "animatediff_motion_lora", "liveportrait",
    "insightface", "facerestore_models", "auraflow", "lumina2", "trt",
    "unet", "ipadapter", "llm", "audio_encoders", "reference_only",
)

SIDECAR_NAME = "model_libs.json"


@dataclass
class ModelLibrary:
    id: str
    name: str
    base_path: str
    enabled: bool = True
    is_default: bool = False
    # 子目录 → 模型类型的映射；空 = 惰性（apply 时按子目录名自动对号）
    mappings: dict[str, str] = field(default_factory=dict)


class ModelPathsService:
    def __init__(self, comfyui_root: Path, config_dir: Path):
        self.root = Path(comfyui_root)
        self.yaml_path = self.root / "extra_model_paths.yaml"
        self.sidecar = Path(config_dir) / SIDECAR_NAME

    # ---------- sidecar（唯一真源） ----------

    def load_libraries(self) -> list[ModelLibrary]:
        if not self.sidecar.exists():
            return []
        try:
            raw = json.loads(self.sidecar.read_text(encoding="utf-8-sig"))
            return [ModelLibrary(**item) for item in raw.get("libraries", [])]
        except (OSError, ValueError, TypeError):
            logger.warning("model_libs.json 损坏，视为空: %s", self.sidecar, exc_info=True)
            return []

    def save_libraries(self, libs: list[ModelLibrary]) -> None:
        import os
        import tempfile

        self.sidecar.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.sidecar.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({"schema_version": SCHEMA_VERSION,
                           "libraries": [asdict(x) for x in libs]},
                          fh, ensure_ascii=False, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.sidecar)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                logger.debug("sidecar 临时文件清理失败", exc_info=True)
            raise

    # ---------- 映射推断 ----------

    def scan_mappings(self, lib: ModelLibrary) -> dict[str, str]:
        """按库目录下的子目录名对号 ComfyUI 类型；对不上的忽略（不猜）。"""
        base = Path(lib.base_path)
        if not base.is_dir():
            return {}
        known = {t.lower(): t for t in KNOWN_TYPES}
        out: dict[str, str] = {}
        for child in sorted(base.iterdir()):
            if child.is_dir() and child.name.lower() in known:
                out[child.name] = known[child.name.lower()]
        return out

    def effective_mappings(self, lib: ModelLibrary) -> dict[str, str]:
        return dict(lib.mappings) or self.scan_mappings(lib)

    # ---------- 渲染与备份 ----------

    def _render(self, libs: list[ModelLibrary]) -> str:
        data: dict[str, dict[str, str]] = {}
        for lib in libs:
            if not lib.enabled:
                continue
            entry: dict[str, str] = {"base_path": lib.base_path}
            for sub, typ in sorted(self.effective_mappings(lib).items()):
                entry[typ] = sub
            data[lib.name or lib.id] = entry
        return yaml.safe_dump(data, allow_unicode=True, sort_keys=False,
                              default_flow_style=False)

    def apply(self) -> dict:
        """sidecar → extra_model_paths.yaml（旧文件先备份）。返回写了几库几映射。"""
        libs = self.load_libraries()
        content = self._render(libs)
        backup = ""
        if self.yaml_path.exists():
            backup = str(self.yaml_path.with_suffix(".yaml.bak"))
            shutil.copy2(self.yaml_path, backup)
        self.yaml_path.parent.mkdir(parents=True, exist_ok=True)
        self.yaml_path.write_text(content, encoding="utf-8")
        n_map = sum(len(self.effective_mappings(l)) for l in libs if l.enabled)
        return {"applied": True, "libraries": sum(1 for l in libs if l.enabled),
                "mappings": n_map, "yaml_path": str(self.yaml_path),
                "backup": backup or None}

    # ---------- 导入现有 yaml ----------

    def import_existing(self) -> int:
        """把 ComfyUI 侧已有 yaml 解析进 sidecar（sidecar 已有则跳过，只增不删）。"""
        if self.sidecar.exists():
            return 0
        if not self.yaml_path.exists():
            return 0
        try:
            data = yaml.safe_load(self.yaml_path.read_text(encoding="utf-8-sig")) or {}
        except yaml.YAMLError:
            logger.warning("现有 yaml 解析失败，不导入", exc_info=True)
            return 0
        libs: list[ModelLibrary] = []
        for i, (name, entry) in enumerate(data.items()):
            if not isinstance(entry, dict) or "base_path" not in entry:
                continue
            # 归一化：值转字符串、剥尾斜杠（yaml 里 true/1 会被解析成 bool/int）
            mappings = {str(k): str(v).rstrip("/\\")
                        for k, v in entry.items() if k != "base_path"}
            libs.append(ModelLibrary(
                id=f"imported_{i}", name=str(name),
                base_path=str(entry["base_path"]).rstrip("/\\"),
                enabled=True, is_default=(i == 0), mappings=mappings))
        if not libs:
            return 0
        self.save_libraries(libs)
        return len(libs)

    # ---------- 校验 ----------

    def validate(self) -> list[str]:
        """体检：路径存在性 + 映射类型合法性。返回问题清单。"""
        problems: list[str] = []
        for lib in self.load_libraries():
            base = Path(lib.base_path)
            base_ok = base.is_dir()
            if not base_ok:
                problems.append(f"[{lib.name}] 路径不存在: {lib.base_path}")
            for sub, typ in lib.mappings.items():
                if typ not in KNOWN_TYPES:
                    problems.append(f"[{lib.name}] 非法映射类型: {sub} → {typ}")
                elif base_ok and not (base / sub).is_dir():
                    problems.append(f"[{lib.name}] 子目录不存在: {sub}")
        return problems


_SKIP_EXTS = {".txt", ".json", ".yaml", ".yml"}


def scan_installed_models(comfyui_root: Path,
                          libraries: list[ModelLibrary],
                          per_type_cap: int = 400) -> dict[str, list[dict]]:
    """盘点已挂载的模型文件：内置 models/<类型> + 各启用库的映射子目录。

    返回 {类型: [{path, name, size, mtime, source}]}，按修改时间新→旧。
    """
    out: dict[str, list[dict]] = {}
    seen: set[str] = set()
    base_dirs: list[tuple[str, Path, str]] = []

    builtin = Path(comfyui_root) / "ComfyUI" / "models"
    if not builtin.is_dir():
        builtin = Path(comfyui_root) / "models"
    if builtin.is_dir():
        for child in sorted(builtin.iterdir()):
            if child.is_dir():
                base_dirs.append((child.name, child, "内置"))

    for lib in libraries:
        if not lib.enabled:
            continue
        for sub, typ in lib.mappings.items():
            base_dirs.append((typ, Path(lib.base_path) / sub, lib.name))

    for typ, d, source in base_dirs:
        if not d.is_dir():
            continue
        bucket = out.setdefault(typ, [])
        for p in d.rglob("*"):
            if len(bucket) >= per_type_cap:
                break
            try:
                if not p.is_file() or p.suffix.lower() in _SKIP_EXTS:
                    continue
                rp = str(p.resolve())
                if rp in seen:
                    continue
                seen.add(rp)
                st = p.stat()
            except OSError:
                logger.debug("模型文件枚举跳过: %s", p, exc_info=True)
                continue
            bucket.append({"path": str(p), "name": p.name,
                           "size": st.st_size, "mtime": st.st_mtime,
                           "source": source})
    for bucket in out.values():
        bucket.sort(key=lambda x: x["mtime"], reverse=True)
    return out

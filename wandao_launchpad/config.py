"""配置存取——全项目唯一入口。

教训对策：
- 原子写（临时文件 + os.replace），绝不半写。
- 多环境从 schema 第一天就有（Mie 是后补的，付了迁移成本）。
- 未知字段保留原样（前向兼容），装载只校验不抛异常（错误收集在 validate 里）。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .constants import SCHEMA_VERSION
from .constants import config_file_path, default_config_dir
from .models import LaunchOptions

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()


@dataclass
class Environment:
    id: str
    name: str = ""
    comfyui_root: str = ""     # 指向含 ComfyUI/ 子目录（或直接含 main.py）的目录
    python_path: str = ""      # python.exe 绝对路径；空 = 用系统 python
    main_script: str = ""      # 空 = 自动探测 ComfyUI/main.py 或 main.py

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "Environment":
        return cls(
            id=str(raw.get("id", "")),
            name=str(raw.get("name", raw.get("id", ""))),
            comfyui_root=str(raw.get("comfyui_root", "")),
            python_path=str(raw.get("python_path", "")),
            main_script=str(raw.get("main_script", "")),
        )


@dataclass
class Mirrors:
    hf: str = ""
    github_proxy: str = ""
    pypi: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict | None) -> "Mirrors":
        raw = raw or {}
        return cls(
            hf=str(raw.get("hf", "")),
            github_proxy=str(raw.get("github_proxy", "")),
            pypi=str(raw.get("pypi", "")),
        )


@dataclass
class Config:
    schema_version: int = SCHEMA_VERSION
    active_env_id: str = ""
    environments: list[Environment] = field(default_factory=list)
    launch: LaunchOptions = field(default_factory=LaunchOptions)
    mirrors: Mirrors = field(default_factory=Mirrors)
    # 前向兼容袋：装载时未知字段原样保留，保存时写回
    _extras: dict = field(default_factory=dict)

    def active_env(self) -> Environment | None:
        for env in self.environments:
            if env.id == self.active_env_id:
                return env
        return None

    def to_dict(self) -> dict:
        data = dict(self._extras)
        data.update(
            schema_version=self.schema_version,
            active_env_id=self.active_env_id,
            environments=[e.to_dict() for e in self.environments],
            launch=self.launch.to_dict(),
            mirrors=self.mirrors.to_dict(),
        )
        return data


def _atomic_write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            logger.debug("临时文件清理失败", exc_info=True)
        raise


_KNOWN_TOP = {"schema_version", "active_env_id", "environments", "launch", "mirrors"}


class ConfigStore:
    """load() → Config；save(Config) → 磁盘。全项目只经它碰 config.json。"""

    def __init__(self, config_dir: Path | None = None):
        self.config_dir = Path(config_dir) if config_dir else default_config_dir()
        self.path = config_file_path(self.config_dir)

    def load(self) -> Config:
        if not self.path.exists():
            return Config()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            logger.warning("config.json 解析失败，回退默认配置: %s", self.path, exc_info=True)
            return Config()
        cfg = Config()
        cfg.schema_version = int(raw.get("schema_version", SCHEMA_VERSION))
        cfg.active_env_id = str(raw.get("active_env_id", ""))
        cfg.environments = [Environment.from_dict(e) for e in raw.get("environments", [])]
        cfg.launch = LaunchOptions.from_dict(raw.get("launch"))
        cfg.mirrors = Mirrors.from_dict(raw.get("mirrors"))
        cfg._extras = {k: v for k, v in raw.items() if k not in _KNOWN_TOP}
        if cfg.environments and cfg.active_env_id not in {e.id for e in cfg.environments}:
            cfg.active_env_id = cfg.environments[0].id
        return cfg

    def save(self, cfg: Config) -> None:
        with _LOCK:
            _atomic_write_json(self.path, cfg.to_dict())

    def update_launch(self, mutate) -> None:
        """读-改-写一把锁内完成，GUI 防抖保存走这里。"""
        with _LOCK:
            cfg = self.load()
            mutate(cfg.launch)
            _atomic_write_json(self.path, cfg.to_dict())

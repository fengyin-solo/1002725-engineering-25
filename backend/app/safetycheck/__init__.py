"""安全巡检配置层：把巡检要点、隐患等级与示例数据做成可维护的配置。

- 配置与示例数据放在 ``backend/app/config_data/`` 下，进版本管理。
- 启动时（见 :func:`app.safetycheck.bootstrap.bootstrap`）校验依赖与配置是否齐全，
  缺项直接抛 :class:`ConfigError` 并指出缺哪一个。
- 导入按配置文件内容的 SHA-256 判重：同一份配置重复导入只生效一次。
- 导入只刷新要点 / 区域 / 等级等主数据，不覆盖已有的巡检业务记录。

业务代码统一通过 :func:`get_safety_config` 读取当前生效配置，不直接碰文件。
"""
from __future__ import annotations

from .loader import (
    SAFETY_CONFIG_PATH,
    SAFETY_SEED_PATH,
    Area,
    Checkpoint,
    ConfigError,
    HazardLevel,
    SafetyConfig,
    SafetySeed,
    SeedRecord,
    load_config,
    load_seed,
)
from .rules import deadline_for
from .importer import ImportReport, SafetyConfigImporter
from .registry import (
    bootstrap,
    get_safety_config,
    importer,
    is_bootstrapped,
    reset_for_tests,
)

__all__ = [
    "SAFETY_CONFIG_PATH",
    "SAFETY_SEED_PATH",
    "Area",
    "Checkpoint",
    "ConfigError",
    "HazardLevel",
    "SafetyConfig",
    "SafetySeed",
    "SeedRecord",
    "ImportReport",
    "SafetyConfigImporter",
    "load_config",
    "load_seed",
    "deadline_for",
    "bootstrap",
    "get_safety_config",
    "importer",
    "is_bootstrapped",
    "reset_for_tests",
]

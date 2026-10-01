"""启动引导与全局注册表。

:func:`bootstrap` 在应用启动（FastAPI lifespan）时执行：
1. 校验第三方依赖与配置是否齐全（缺项由 loader 汇总报出，直接中断启动）；
2. 幂等导入主数据与示例数据；
3. 之后业务代码通过 :func:`get_safety_config` 读取当前生效配置。

``ensure_ready`` 让非 HTTP 入口（脚本、直接调用 service 的单测）也会惰性自检，
不会因为忘了走 lifespan 而用到空配置。
"""
from __future__ import annotations

from .importer import ImportReport, SafetyConfigImporter
from .loader import (
    SAFETY_CONFIG_PATH,
    SAFETY_SEED_PATH,
    ConfigError,
    SafetyConfig,
    SafetySeed,
    load_config,
    load_seed,
)

_importer = SafetyConfigImporter()
_last_report: ImportReport | None = None


def importer() -> SafetyConfigImporter:
    return _importer


def is_bootstrapped() -> bool:
    return _importer._config is not None


def get_safety_config() -> SafetyConfig:
    """返回当前生效的巡检配置；尚未引导时惰性自检并引导一次。"""
    if not is_bootstrapped():
        bootstrap()
    return _importer.config


def bootstrap(*, force: bool = False) -> ImportReport:
    """加载、校验并幂等导入配置与示例数据。

    配置缺失或依赖缺失时抛 :class:`ConfigError`，由启动入口转成「启动失败」。
    """
    global _last_report
    config: SafetyConfig = load_config(SAFETY_CONFIG_PATH)
    seed: SafetySeed = load_seed(config, SAFETY_SEED_PATH)
    _last_report = _importer.apply(config, seed, force=force)
    return _last_report


def last_report() -> ImportReport | None:
    return _last_report


def reset_for_tests() -> None:
    """重置全局引导状态；仅供测试隔离使用。"""
    global _last_report
    _importer.__init__()
    _last_report = None

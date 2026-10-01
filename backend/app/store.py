"""内存数据仓库：给每个业务模块准备一份可筛选、可流转的示例数据。

真实项目里这里会换成数据库访问层；当前实现只依赖标准库，保证克隆下来就能起。

安全巡检模块不走 Python 内置示例数据：区域要点、隐患等级与示例记录都从
``backend/config/`` 下的配置文件加载（见 ``app/inspection.py``）。
仓库初始化时会先校验配置与依赖再幂等导入，缺项直接抛出 ``InspectionConfigError``，
服务因此无法启动，错误消息会指出缺的是哪一项。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.inspection import (
    ImportReport,
    InspectionConfigError,
    SafetyConfig,
    import_seed_records,
    load_and_validate,
)
from app.seed import SEED_ROWS

# 安全巡检模块的表名，单独由配置文件供给示例数据。
SAFETY_MODULE = "safetycheck"


class Store:
    def __init__(self, *, autobootstrap: bool = True) -> None:
        self._tables: dict[str, list[dict[str, Any]]] = {
            name: [dict(row) for row in rows]
            for name, rows in SEED_ROWS.items()
            if name != SAFETY_MODULE
        }
        self.safety_config: SafetyConfig | None = None
        self.safety_report: ImportReport | None = None
        if autobootstrap:
            # 启动引导：配置/示例数据有任何缺项，这里直接抛 InspectionConfigError 终止启动，
            # 错误消息会指出缺的是哪一项。
            self.bootstrap_safety()

    # -- 安全巡检配置引导 -------------------------------------------------- #

    def bootstrap_safety(
        self,
        config_path: Path | None = None,
        seed_path: Path | None = None,
    ) -> ImportReport:
        """加载并校验配置与示例数据，然后幂等导入巡检记录。

        - 首次调用（启动）：整份配置生效，示例记录全部插入；
        - 再次调用（运维重复导入）：配置整体替换，示例记录按巡检编号判重，
          已有的巡检记录（含运行期新建、已流转的）一行都不会被覆盖。
        """
        config, normalized = load_and_validate(config_path, seed_path)
        rows = self._tables.setdefault(SAFETY_MODULE, [])
        report = import_seed_records(rows, normalized, config)
        self.safety_config = config
        self.safety_report = report
        return report

    # -- 通用表操作 -------------------------------------------------------- #

    def module_names(self) -> list[str]:
        return sorted(self._tables)

    def rows(self, module: str) -> list[dict[str, Any]]:
        return self._tables.setdefault(module, [])

    def find(self, module: str, entry_id: int) -> dict[str, Any] | None:
        for row in self.rows(module):
            if int(row.get("id", 0)) == entry_id:
                return row
        return None

    def overview(self) -> dict[str, object]:
        modules: list[dict[str, object]] = []
        for name in self.module_names():
            rows = self.rows(name)
            modules.append({
                "name": name,
                "created": len(rows),
                "pending": sum(1 for row in rows if row.get("pending")),
                "abnormal": sum(1 for row in rows if row.get("abnormal")),
            })
        cards = [
            {"label": "业务模块", "value": len(modules)},
            {"label": "今日新增", "value": sum(int(item["created"]) for item in modules)},
            {"label": "待处理", "value": sum(int(item["pending"]) for item in modules)},
            {"label": "异常量", "value": sum(int(item["abnormal"]) for item in modules)},
        ]
        return {"cards": cards, "modules": modules}


def bootstrap(config_path: Path | None = None, seed_path: Path | None = None) -> "Store":
    """供启动入口与命令行显式调用：校验配置依赖并幂等导入示例数据。

    坏配置会在这里抛 InspectionConfigError，由调用方决定是让进程退出（CLI 返回 2）
    还是让服务启动失败（uvicorn 加载 app.main 时抛出）。
    """
    instance = Store(autobootstrap=False)
    instance.bootstrap_safety(config_path, seed_path)
    return instance


# 模块级单例延迟到首次使用时创建，避免「只是 import 一下模块」（例如 CLI 换了
# SAFETY_CONFIG_DIR 想先校验别处的配置）就被默认配置的引导错误打断。
_store: Store | None = None


def __getattr__(name: str) -> Any:
    global _store
    if name == "store":
        if _store is None:
            _store = Store()
        return _store
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def set_store(instance: Store) -> None:
    """测试或离线脚本注入已引导的仓库实例。"""
    global _store
    _store = instance

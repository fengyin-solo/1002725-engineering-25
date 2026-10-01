"""安全巡检配置与示例数据的幂等导入。

两条核心保证：

1. **同一份配置重复导入只生效一次**：以配置文件内容的 SHA-256 作为指纹。
   指纹没变就直接返回 ``changed=False``，不再做任何写入。
2. **重复导入不覆盖已有巡检记录**：导入主数据（区域 / 等级 / 要点）是无副作用的
   引用数据；示例数据按「巡检编号」判重，已存在（含运行期新建、被状态流转改过）
   的记录一律跳过，只补登记缺失的编号。

因此无论启动多少次、在几个环境启动，只要配置文件相同，仓库里的初始数据就相同，
且运行期产生的巡检记录不会被初始化动作抹掉。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.store import store

from .loader import SafetyConfig, SafetySeed, load_config, load_seed

MODULE = "safetycheck"

# 业务记录展示用的中文列（与前端表格列保持一致）
F_NUMBER = "巡检编号"
F_AREA = "巡检区域"
F_DATE = "巡检日期"
F_PERSON = "巡检人员"
F_HAZARD = "发现隐患"
F_ACTION = "整改措施"
F_DEADLINE = "整改期限"
F_STATUS_TEXT = "巡检状态"
# 稳定编码与主数据引用，额外挂在记录上供一致性校验与后续处理使用
F_AREA_CODE = "_area_code"
F_LEVEL_CODE = "_hazard_level"
F_POINT_CODES = "_checkpoint_codes"


@dataclass
class ImportReport:
    changed: bool
    config_hash: str
    seed_hash: str
    imported_records: int = 0          # 本次新补登记的示例记录数
    skipped_existing_records: int = 0  # 因巡检编号已存在而跳过、未覆盖的条数
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "changed": self.changed,
            "config_hash": self.config_hash,
            "seed_hash": self.seed_hash,
            "imported_records": self.imported_records,
            "skipped_existing_records": self.skipped_existing_records,
            "notes": self.notes,
        }


class SafetyConfigImporter:
    """持有当前生效配置指纹，负责把配置 / 示例数据幂等地应用到内存仓库。"""

    def __init__(self) -> None:
        self._config: SafetyConfig | None = None
        self._seed: SafetySeed | None = None
        self._applied_config_hash: str | None = None
        self._applied_seed_hash: str | None = None

    @property
    def config(self) -> SafetyConfig:
        if self._config is None:
            raise RuntimeError("安全巡检配置尚未加载，请先执行 bootstrap()")
        return self._config

    def is_applied(self, config: SafetyConfig, seed: SafetySeed | None = None) -> bool:
        if self._applied_config_hash != config.content_hash:
            return False
        if seed is not None and self._applied_seed_hash != seed.content_hash:
            return False
        return True

    def _build_seed_row(self, record, row_id: int) -> dict[str, object]:
        """把示例记录转成与业务表一致的行；状态口径与 SafetycheckService 对齐。"""
        pending = record.状态 != "已闭合"
        abnormal = record.状态 in {"巡检中", "待整改"}
        point_texts: list[str] = []
        assert self._config is not None
        for code in record.检查要点:
            point = self._config.checkpoint(code)
            if point is not None:
                point_texts.append(point.text)
        return {
            "id": row_id,
            "status": record.状态,
            "pending": pending,
            "abnormal": abnormal,
            F_NUMBER: record.巡检编号,
            F_AREA: self._config.area_name(record.区域) or record.区域,
            F_DATE: record.巡检日期,
            F_PERSON: record.巡检人员,
            F_HAZARD: record.发现隐患,
            F_ACTION: record.整改措施,
            F_DEADLINE: record.整改期限,
            F_STATUS_TEXT: record.状态,
            F_AREA_CODE: record.区域,
            F_LEVEL_CODE: record.隐患等级,
            F_POINT_CODES: list(record.检查要点),
            "检查要点": "；".join(text for text in point_texts if text),
        }

    def apply(
        self,
        config: SafetyConfig | None = None,
        seed: SafetySeed | None = None,
        *,
        force: bool = False,
    ) -> ImportReport:
        """幂等应用配置与示例数据。

        ``force`` 仅表示重新从磁盘读取并校验；只要内容指纹与已生效配置相同，
        就整体跳过（changed=False），从而「同一份配置重复导入只生效一次」。
        """
        config = config or load_config()
        seed = seed or load_seed(config)
        self._config = config

        if self.is_applied(config, seed):
            return ImportReport(
                changed=False,
                config_hash=config.content_hash,
                seed_hash=seed.content_hash,
                skipped_existing_records=len(
                    [r for r in seed.records if store.find_by_key(MODULE, F_NUMBER, r.巡检编号)]
                ),
                notes=["配置内容未变化，重复导入已跳过（同一份配置只生效一次），已有巡检记录保持不变"],
            )

        imported = 0
        skipped = 0
        notes: list[str] = []

        # 示例数据：按巡检编号判重，只补登记，绝不覆盖已有巡检记录。
        rows = store.rows(MODULE)
        for record in seed.records:
            existing = store.find_by_key(MODULE, F_NUMBER, record.巡检编号)
            if existing is not None:
                skipped += 1
                continue
            rows.append(self._build_seed_row(record, store.next_id(MODULE)))
            imported += 1

        first_import = self._applied_config_hash is None
        self._applied_config_hash = config.content_hash
        self._applied_seed_hash = seed.content_hash

        if imported:
            notes.append(f"已按示例数据补登记 {imported} 条巡检记录")
        if skipped:
            notes.append(f"{skipped} 条同编号巡检记录已存在，按幂等规则跳过、未覆盖")
        if not imported and not skipped:
            notes.append("示例数据为空，未写入巡检记录")
        if not first_import:
            notes.append("主数据（区域/等级/检查要点）已按最新配置刷新，已有巡检记录保持不变")

        return ImportReport(
            changed=True,
            config_hash=config.content_hash,
            seed_hash=seed.content_hash,
            imported_records=imported,
            skipped_existing_records=skipped,
            notes=notes,
        )

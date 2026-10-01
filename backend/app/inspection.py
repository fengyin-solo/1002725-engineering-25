"""安全巡检配置：巡检要点（按巡检区域分组）、隐患等级与整改期限默认天数。

设计目标（对应项目文档《安全巡检配置说明》）：

- 区域、要点、等级、天数全部来自 ``backend/config/*.json``，业务代码不写死，
  换现场只改配置文件；
- 启动时一次性校验：配置文件缺失、配置缺项、示例数据与配置对不上，都直接报错
  并指出缺的是哪一个；
- 示例数据按巡检编号幂等导入：重复导入只生效一次，已存在的巡检记录绝不覆盖；
- 整改期限按「发现日期 + 等级默认天数」确定性计算，不读系统时钟，
  同一份配置与示例数据在两个环境跑出来的结论相同。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

# 巡检记录的标准状态序列，与 services/safetycheck.py 保持一致。
STATUS_ORDER = ["待巡检", "巡检中", "待整改", "已闭合"]

# 示例数据里必须出现的业务字段（id、status、pending、abnormal 由导入时补齐）。
RECORD_REQUIRED_FIELDS = ["巡检编号", "巡检区域", "巡检要点", "巡检日期", "巡检人员", "巡检状态"]


class InspectionConfigError(ValueError):
    """配置或示例数据不满足启动要求时抛出；消息里会点名缺的是哪一项。"""


@dataclass(frozen=True)
class Checkpoint:
    code: str
    name: str
    risk_level: str


@dataclass(frozen=True)
class InspectionArea:
    code: str
    name: str
    checkpoints: list[Checkpoint]


@dataclass(frozen=True)
class RiskLevel:
    code: str
    name: str
    deadline_days: int


@dataclass(frozen=True)
class SafetyConfig:
    """校验通过后的安全巡检配置，业务代码只读这里，不直接碰原始 JSON。"""

    schema_version: int
    areas: list[InspectionArea]
    risk_levels: list[RiskLevel]
    area_by_name: dict[str, InspectionArea] = field(default_factory=dict, repr=False)
    checkpoint_by_key: dict[tuple[str, str], Checkpoint] = field(default_factory=dict, repr=False)
    risk_by_name: dict[str, RiskLevel] = field(default_factory=dict, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """给配置查询接口用：输出稳定有序，方便两个环境逐项比对。"""
        return {
            "schema_version": self.schema_version,
            "areas": [
                {
                    "code": area.code,
                    "name": area.name,
                    "checkpoints": [
                        {"code": cp.code, "name": cp.name, "risk_level": cp.risk_level}
                        for cp in area.checkpoints
                    ],
                }
                for area in self.areas
            ],
            "risk_levels": [
                {"code": lv.code, "name": lv.name, "deadline_days": lv.deadline_days}
                for lv in self.risk_levels
            ],
        }

    def risk_level_names(self) -> list[str]:
        return [lv.name for lv in self.risk_levels]


@dataclass(frozen=True)
class ImportReport:
    """一次（配置 + 示例数据）导入的结果。"""

    areas: int
    checkpoints: int
    risk_levels: int
    inserted: int
    skipped: int
    skipped_ids: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "areas": self.areas,
            "checkpoints": self.checkpoints,
            "risk_levels": self.risk_levels,
            "seed_inserted": self.inserted,
            "seed_skipped": self.skipped,
            "skipped_ids": self.skipped_ids,
        }


# --------------------------------------------------------------------------- #
# 加载
# --------------------------------------------------------------------------- #

def default_config_dir() -> Path:
    """默认配置目录：backend/config。可用环境变量 SAFETY_CONFIG_DIR 覆盖。"""
    import os

    override = os.environ.get("SAFETY_CONFIG_DIR")
    if override:
        return Path(override)
    return Path(__file__).resolve().parent.parent / "config"


def _load_json(path: Path, *, what: str) -> Any:
    if not path.exists():
        raise InspectionConfigError(
            f"{what}缺失：找不到文件 {path}，请确认配置目录已随版本库一起部署"
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise InspectionConfigError(f"{what}格式错误：{path} 第 {exc.lineno} 行附近不是合法 JSON：{exc.msg}") from exc


def load_config(path: Path | None = None) -> SafetyConfig:
    path = path or (default_config_dir() / "safetycheck.json")
    raw = _load_json(path, what="安全巡检配置")
    return parse_config(raw, source=str(path))


def load_seed_records(path: Path | None = None) -> list[dict[str, Any]]:
    path = path or (default_config_dir() / "safetycheck.seed.json")
    raw = _load_json(path, what="安全巡检示例数据")
    if not isinstance(raw, dict) or not isinstance(raw.get("records"), list):
        raise InspectionConfigError(f"安全巡检示例数据结构错误：{path} 顶层必须是包含 records 数组的对象")
    return list(raw["records"])


# --------------------------------------------------------------------------- #
# 校验
# --------------------------------------------------------------------------- #

def _require(data: Any, key: str, *, owner: str, errors: list[str]) -> Any:
    if not isinstance(data, dict) or key not in data or data[key] in (None, ""):
        errors.append(f"{owner}缺少必填项「{key}」")
        return None
    return data[key]


def parse_config(raw: Any, *, source: str = "safetycheck.json") -> SafetyConfig:
    """把原始 JSON 校验成 SafetyConfig；缺项/重复/悬空引用全部点名报错。"""
    errors: list[str] = []
    if not isinstance(raw, dict):
        raise InspectionConfigError(f"安全巡检配置 {source} 顶层必须是对象")

    raw_areas = raw.get("areas")
    raw_levels = raw.get("risk_levels")
    if not isinstance(raw_areas, list) or not raw_areas:
        errors.append("安全巡检配置缺少必填项「areas」（至少配置一个巡检区域）")
        raw_areas = []
    if not isinstance(raw_levels, list) or not raw_levels:
        errors.append("安全巡检配置缺少必填项「risk_levels」（至少配置一个隐患等级）")
        raw_levels = []

    # 先解析等级，要点上的默认隐患等级要引用它。
    levels: list[RiskLevel] = []
    seen_level_codes: set[str] = set()
    seen_level_names: set[str] = set()
    for index, item in enumerate(raw_levels, start=1):
        owner = f"隐患等级第 {index} 项"
        if not isinstance(item, dict):
            errors.append(f"{owner}必须是对象")
            continue
        code = _require(item, "code", owner=owner, errors=errors)
        name = _require(item, "name", owner=owner, errors=errors)
        days = _require(item, "deadline_days", owner=owner, errors=errors)
        if days is not None and (not isinstance(days, int) or isinstance(days, bool) or days <= 0):
            errors.append(f"{owner}（{name or code}）的「deadline_days」必须是正整数，实际为 {days!r}")
        if code and code in seen_level_codes:
            errors.append(f"隐患等级编码重复：{code}")
        if name and name in seen_level_names:
            errors.append(f"隐患等级名称重复：{name}")
        if code:
            seen_level_codes.add(code)
        if name:
            seen_level_names.add(name)
        if code and name and isinstance(days, int) and not isinstance(days, bool) and days > 0:
            levels.append(RiskLevel(code=str(code), name=str(name), deadline_days=days))

    level_names = {lv.name for lv in levels}

    # 再解析区域与要点。
    areas: list[InspectionArea] = []
    seen_area_codes: set[str] = set()
    seen_area_names: set[str] = set()
    seen_checkpoint_codes: set[str] = set()
    for a_index, raw_area in enumerate(raw_areas, start=1):
        if not isinstance(raw_area, dict):
            errors.append(f"巡检区域第 {a_index} 项必须是对象")
            continue
        owner = f"巡检区域第 {a_index} 项"
        code = _require(raw_area, "code", owner=owner, errors=errors)
        name = _require(raw_area, "name", owner=owner, errors=errors)
        raw_points = raw_area.get("checkpoints")
        if not isinstance(raw_points, list) or not raw_points:
            errors.append(f"巡检区域「{name or code or a_index}」缺少必填项「checkpoints」（至少一个巡检要点）")
            raw_points = []
        if code and code in seen_area_codes:
            errors.append(f"巡检区域编码重复：{code}")
        if name and name in seen_area_names:
            errors.append(f"巡检区域名称重复：{name}")
        if code:
            seen_area_codes.add(code)
        if name:
            seen_area_names.add(name)

        points: list[Checkpoint] = []
        seen_point_names: set[str] = set()
        for p_index, raw_point in enumerate(raw_points, start=1):
            p_owner = f"巡检区域「{name or code or a_index}」的要点第 {p_index} 项"
            if not isinstance(raw_point, dict):
                errors.append(f"{p_owner}必须是对象")
                continue
            p_code = _require(raw_point, "code", owner=p_owner, errors=errors)
            p_name = _require(raw_point, "name", owner=p_owner, errors=errors)
            p_level = _require(raw_point, "risk_level", owner=p_owner, errors=errors)
            if p_code and p_code in seen_checkpoint_codes:
                errors.append(f"巡检要点编码重复：{p_code}")
            if p_name and p_name in seen_point_names:
                errors.append(f"巡检区域「{name}」内要点名称重复：{p_name}")
            if p_level is not None and p_level not in level_names:
                errors.append(
                    f"巡检要点「{p_name or p_code}」引用的隐患等级「{p_level}」未在 risk_levels 中配置，"
                    f"可选值：{'、'.join(sorted(level_names)) or '（空）'}"
                )
            if p_code:
                seen_checkpoint_codes.add(p_code)
            if p_name:
                seen_point_names.add(p_name)
            if p_code and p_name and p_level in level_names:
                points.append(Checkpoint(code=str(p_code), name=str(p_name), risk_level=str(p_level)))

        if code and name:
            areas.append(InspectionArea(code=str(code), name=str(name), checkpoints=points))

    if errors:
        raise InspectionConfigError("安全巡检配置校验失败（" + "；".join(errors) + "）")

    return SafetyConfig(
        schema_version=int(raw.get("schema_version", 1)),
        areas=areas,
        risk_levels=levels,
        area_by_name={a.name: a for a in areas},
        checkpoint_by_key={
            (a.name, cp.name): cp for a in areas for cp in a.checkpoints
        },
        risk_by_name={lv.name: lv for lv in levels},
    )


def _parse_iso_date(value: Any, *, owner: str, field_name: str, errors: list[str]) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        errors.append(f"{owner}的「{field_name}」不是合法日期（应为 YYYY-MM-DD），实际为 {value!r}")
        return None


def validate_seed_records(records: list[dict[str, Any]], config: SafetyConfig) -> list[dict[str, Any]]:
    """校验示例数据与配置一致：区域/要点/等级必须引用得到，期限必须与配置算得一致。"""
    errors: list[str] = []
    seen_ids: set[str] = set()
    normalized: list[dict[str, Any]] = []

    for index, record in enumerate(records, start=1):
        owner = f"示例数据第 {index} 条"
        if not isinstance(record, dict):
            errors.append(f"{owner}必须是对象")
            continue
        values = {key: record.get(key) for key in RECORD_REQUIRED_FIELDS}
        for key in RECORD_REQUIRED_FIELDS:
            if record.get(key) in (None, ""):
                errors.append(f"{owner}缺少必填项「{key}」")

        rec_id = str(record.get("巡检编号") or f"# {index}")
        if record.get("巡检编号"):
            if rec_id in seen_ids:
                errors.append(f"示例数据巡检编号重复：{rec_id}")
            seen_ids.add(rec_id)
            owner = f"示例数据「{rec_id}」"

        area_name = record.get("巡检区域")
        point_name = record.get("巡检要点")
        if area_name and area_name not in config.area_by_name:
            errors.append(
                f"{owner}的巡检区域「{area_name}」未在配置中定义，"
                f"可选区域：{'、'.join(a.name for a in config.areas)}"
            )
        elif area_name and point_name:
            checkpoint = config.checkpoint_by_key.get((area_name, point_name))
            if checkpoint is None:
                configured = [cp.name for cp in config.area_by_name[area_name].checkpoints]
                errors.append(
                    f"{owner}的巡检要点「{point_name}」不属于配置中的巡检区域「{area_name}」，"
                    f"该区域已配置要点：{'、'.join(configured)}"
                )

        status = record.get("巡检状态")
        if status and status not in STATUS_ORDER:
            errors.append(
                f"{owner}的巡检状态「{status}」非法，可选值：{'、'.join(STATUS_ORDER)}"
            )

        risk_name = record.get("隐患等级")
        found_desc = record.get("发现隐患")
        found_date = _parse_iso_date(record.get("发现日期"), owner=owner, field_name="发现日期", errors=errors)
        due_raw = record.get("整改期限")
        due_date = _parse_iso_date(due_raw, owner=owner, field_name="整改期限", errors=errors) if due_raw not in (None, "") else None

        has_hazard = found_desc not in (None, "")
        if has_hazard:
            if not risk_name:
                errors.append(f"{owner}已填写「发现隐患」，缺少必填项「隐患等级」")
            elif risk_name not in config.risk_by_name:
                errors.append(
                    f"{owner}的隐患等级「{risk_name}」未在配置中定义，"
                    f"可选等级：{'、'.join(config.risk_level_names())}"
                )
            if not found_date:
                errors.append(f"{owner}已填写「发现隐患」，缺少必填项「发现日期」（用于按等级计算整改期限）")
            if risk_name in config.risk_by_name and found_date:
                expected = compute_deadline(found_date, config.risk_by_name[risk_name].deadline_days)
                if due_date is not None and due_date != expected:
                    errors.append(
                        f"{owner}的整改期限 {due_date.isoformat()} 与配置不一致："
                        f"隐患等级「{risk_name}」默认 {config.risk_by_name[risk_name].deadline_days} 天，"
                        f"发现日期 {found_date.isoformat()}，应为 {expected.isoformat()}"
                    )

        if errors:
            continue

        normalized_record = dict(values)
        normalized_record["隐患等级"] = risk_name
        normalized_record["发现隐患"] = found_desc or ""
        normalized_record["整改措施"] = record.get("整改措施") or ""
        normalized_record["发现日期"] = found_date.isoformat() if found_date else None
        if due_date is not None:
            normalized_record["整改期限"] = due_date.isoformat()
        elif has_hazard:
            normalized_record["整改期限"] = compute_deadline(
                found_date, config.risk_by_name[risk_name].deadline_days
            ).isoformat()
        else:
            normalized_record["整改期限"] = None
        normalized.append(normalized_record)

    if errors:
        raise InspectionConfigError("安全巡检示例数据校验失败（" + "；".join(errors) + "）")
    return normalized


# --------------------------------------------------------------------------- #
# 业务规则与导入
# --------------------------------------------------------------------------- #

def compute_deadline(discovered_on: date, deadline_days: int) -> date:
    """发现日期 + 配置天数。纯函数，不接触系统时钟，保证跨环境结论一致。"""
    from datetime import timedelta

    return discovered_on + timedelta(days=deadline_days)


def build_record_row(normalized: dict[str, Any], row_id: int) -> dict[str, Any]:
    """把校验过的示例记录转成内存仓库行：补齐 id/status/pending/abnormal。"""
    status = normalized["巡检状态"]
    row = {
        "id": row_id,
        "status": status,
        "pending": status != STATUS_ORDER[-1],
        "abnormal": status == "待整改",
        "巡检编号": normalized["巡检编号"],
        "巡检区域": normalized["巡检区域"],
        "巡检要点": normalized["巡检要点"],
        "隐患等级": normalized["隐患等级"],
        "巡检日期": normalized["巡检日期"],
        "巡检人员": normalized["巡检人员"],
        "发现隐患": normalized["发现隐患"],
        "整改措施": normalized["整改措施"],
        "发现日期": normalized["发现日期"],
        "整改期限": normalized["整改期限"],
        "巡检状态": status,
    }
    return row


def import_seed_records(
    existing_rows: list[dict[str, Any]],
    normalized: list[dict[str, Any]],
    config: SafetyConfig,
) -> ImportReport:
    """幂等导入：按巡检编号判重，已存在的记录整行保留，不做任何覆盖。

    返回的 report 说明本次新增了几条、因已存在而跳过了哪几条；
    同一份示例数据第二次导入必然是 inserted=0。
    """
    existing_ids = {str(row.get("巡检编号")) for row in existing_rows}
    next_id = max((int(row.get("id", 0)) for row in existing_rows), default=0) + 1
    inserted = 0
    skipped_ids: list[str] = []
    for item in normalized:
        rec_id = str(item["巡检编号"])
        if rec_id in existing_ids:
            skipped_ids.append(rec_id)
            continue
        existing_rows.append(build_record_row(item, next_id))
        existing_ids.add(rec_id)
        next_id += 1
        inserted += 1
    return ImportReport(
        areas=len(config.areas),
        checkpoints=sum(len(area.checkpoints) for area in config.areas),
        risk_levels=len(config.risk_levels),
        inserted=inserted,
        skipped=len(skipped_ids),
        skipped_ids=skipped_ids,
    )


def load_and_validate(
    config_path: Path | None = None,
    seed_path: Path | None = None,
) -> tuple[SafetyConfig, list[dict[str, Any]]]:
    """启动入口：读文件 → 校验配置 → 用配置反查示例数据，任一缺项直接报错。"""
    config = load_config(config_path)
    raw_records = load_seed_records(seed_path)
    normalized = validate_seed_records(raw_records, config)
    return config, normalized

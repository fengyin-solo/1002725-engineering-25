"""安全巡检配置的读取与启动校验。

设计原则：
- 只读标准数据结构 + YAML，解析结果用 dataclass 表达，业务代码不直接碰 dict。
- 校验把「缺了什么」一次性收集齐再抛 :class:`ConfigError`，报错信息能直接定位到
  缺的是哪个区域、哪条要点、哪个字段，而不是只抛第一个错误。
- 校验不依赖业务代码，改配置后重启即可发现问题。
"""
from __future__ import annotations

import importlib
import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

_CONFIG_DIR = Path(
    os.environ.get("SAFETY_CONFIG_DIR", Path(__file__).resolve().parent.parent / "config_data")
)
SAFETY_CONFIG_PATH = _CONFIG_DIR / "safetycheck.yaml"
SAFETY_SEED_PATH = _CONFIG_DIR / "safetycheck.seed.yaml"


class ConfigError(Exception):
    """配置或依赖不满足启动条件；``problems`` 里是逐项可读的缺项说明。"""

    def __init__(self, problems: list[str] | str) -> None:
        self.problems = [problems] if isinstance(problems, str) else problems
        super().__init__("；".join(self.problems))


@dataclass(frozen=True)
class HazardLevel:
    code: str
    name: str
    default_deadline_days: int


@dataclass(frozen=True)
class Area:
    code: str
    name: str


@dataclass(frozen=True)
class Checkpoint:
    code: str
    text: str
    area: str
    risk_level: str


@dataclass(frozen=True)
class Requirement:
    """启动时要确认的第三方依赖。"""

    name: str
    import_name: str
    install: str
    purpose: str


@dataclass(frozen=True)
class SafetyConfig:
    version: int
    requirements: tuple[Requirement, ...]
    hazard_levels: tuple[HazardLevel, ...]
    areas: tuple[Area, ...]
    checkpoints: tuple[Checkpoint, ...]
    source_path: Path
    content_hash: str

    @property
    def area_codes(self) -> set[str]:
        return {area.code for area in self.areas}

    @property
    def level_codes(self) -> set[str]:
        return {level.code for level in self.hazard_levels}

    def area_name(self, code: str) -> str | None:
        for area in self.areas:
            if area.code == code:
                return area.name
        return None

    def level(self, code: str) -> HazardLevel | None:
        for level in self.hazard_levels:
            if level.code == code:
                return level
        return None

    def level_name(self, code: str) -> str | None:
        level = self.level(code)
        return level.name if level else None

    def checkpoint(self, code: str) -> Checkpoint | None:
        for point in self.checkpoints:
            if point.code == code:
                return point
        return None

    def checkpoints_by_area(self, area: str) -> tuple[Checkpoint, ...]:
        return tuple(point for point in self.checkpoints if point.area == area)


@dataclass(frozen=True)
class SeedRecord:
    巡检编号: str
    区域: str
    巡检日期: str
    巡检人员: str
    状态: str
    检查要点: tuple[str, ...] = field(default_factory=tuple)
    隐患等级: str | None = None
    发现隐患: str | None = None
    整改措施: str | None = None
    整改期限: str | None = None


@dataclass(frozen=True)
class SafetySeed:
    records: tuple[SeedRecord, ...]
    source_path: Path
    content_hash: str


def _read_yaml(path: Path) -> Any:
    if not path.exists():
        raise ConfigError(f"缺少配置文件：{path}（请确认配置已随版本管理一起检出）")
    try:
        import yaml  # noqa: F401  # 依赖在 verify_dependencies 已校验，这里再兜底一次
    except Exception as exc:  # pragma: no cover - 正常路径已先校验依赖
        raise ConfigError(f"缺少依赖 yaml（PyYAML），无法读取 {path}：{exc}")
    import yaml

    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError(f"配置文件 {path} 不是合法 YAML：{exc}")
    if not isinstance(data, dict):
        raise ConfigError(f"配置文件 {path} 的顶层必须是键值映射（mapping）")
    return data


def verify_dependencies(raw: dict[str, Any], *, where: Path) -> None:
    """确认 requires 里声明的第三方依赖都能导入，缺哪个报哪个。"""
    problems: list[str] = []
    requirements = raw.get("requires")
    if requirements is None:
        problems.append(f"{where}: 缺少 requires 依赖声明段")
        raise ConfigError(problems)
    if not isinstance(requirements, list) or not requirements:
        raise ConfigError(f"{where}: requires 必须是非空列表")
    for index, item in enumerate(requirements):
        where_desc = f"{where} requires[{index + 1}]"
        if not isinstance(item, dict):
            problems.append(f"{where_desc}: 依赖项必须是映射，当前为 {type(item).__name__}")
            continue
        for key in ("name", "import_name", "install", "purpose"):
            if not str(item.get(key) or "").strip():
                problems.append(f"{where_desc}: 缺少字段 {key}")
        if problems and any("缺少字段" in p for p in problems):
            continue
        import_name = str(item["import_name"]).strip()
        try:
            importlib.import_module(import_name)
        except Exception:
            problems.append(
                f"{where_desc}: 缺少依赖「{item['name']}」（import {import_name} 失败），"
                f"请先执行 {item['install']}；用途：{item['purpose']}"
            )
    if problems:
        raise ConfigError(problems)


def _parse_date(value: Any, *, where: str, problems: list[str]) -> str | None:
    if value is None or str(value).strip() == "":
        problems.append(f"{where}: 缺少日期")
        return None
    if isinstance(value, date) and not isinstance(value, bool):
        return value.isoformat()
    text = str(value).strip()
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        problems.append(f"{where}: 日期「{text}」不是 YYYY-MM-DD 格式")
        return None


def load_config(path: Path | None = None) -> SafetyConfig:
    """读取并校验巡检配置；任何缺项都会汇总到 :class:`ConfigError`。"""
    path = path or SAFETY_CONFIG_PATH
    raw = _read_yaml(path)
    verify_dependencies(raw, where=path)

    problems: list[str] = []
    version = raw.get("version")
    if not isinstance(version, int):
        problems.append(f"{path}: 缺少整数 version 版本号")

    requirements = tuple(
        Requirement(
            name=str(item["name"]).strip(),
            import_name=str(item["import_name"]).strip(),
            install=str(item["install"]).strip(),
            purpose=str(item["purpose"]).strip(),
        )
        for item in raw["requires"]
    )

    # ---- 隐患等级 ----
    levels: list[HazardLevel] = []
    seen_level_codes: set[str] = set()
    raw_levels = raw.get("hazard_levels")
    if not isinstance(raw_levels, list) or not raw_levels:
        problems.append(f"{path}: 缺少非空的 hazard_levels（隐患等级与默认整改天数）")
    else:
        for index, item in enumerate(raw_levels):
            where = f"{path} hazard_levels[{index + 1}]"
            if not isinstance(item, dict):
                problems.append(f"{where}: 必须是映射")
                continue
            code = str(item.get("code") or "").strip()
            name = str(item.get("name") or "").strip()
            days = item.get("default_deadline_days")
            if not code:
                problems.append(f"{where}: 缺少 code")
            if not name:
                problems.append(f"{where}: 缺少 name")
            if not isinstance(days, int) or isinstance(days, bool) or days < 0:
                problems.append(f"{where}: default_deadline_days 必须是不小于 0 的整数")
            if code and code in seen_level_codes:
                problems.append(f"{where}: 隐患等级编码 {code} 重复")
            if code:
                seen_level_codes.add(code)
            if code and name and isinstance(days, int) and not isinstance(days, bool) and days >= 0:
                levels.append(HazardLevel(code=code, name=name, default_deadline_days=days))

    # ---- 巡检区域 ----
    areas: list[Area] = []
    seen_area_codes: set[str] = set()
    raw_areas = raw.get("areas")
    if not isinstance(raw_areas, list) or not raw_areas:
        problems.append(f"{path}: 缺少非空的 areas（巡检区域分组）")
    else:
        for index, item in enumerate(raw_areas):
            where = f"{path} areas[{index + 1}]"
            if not isinstance(item, dict):
                problems.append(f"{where}: 必须是映射")
                continue
            code = str(item.get("code") or "").strip()
            name = str(item.get("name") or "").strip()
            if not code:
                problems.append(f"{where}: 缺少 code")
            if not name:
                problems.append(f"{where}: 缺少 name")
            if code and code in seen_area_codes:
                problems.append(f"{where}: 区域编码 {code} 重复")
            if code:
                seen_area_codes.add(code)
            if code and name:
                areas.append(Area(code=code, name=name))

    # ---- 检查要点分组 ----
    checkpoints: list[Checkpoint] = []
    seen_point_codes: set[str] = set()
    groups_covering_areas: set[str] = set()
    raw_groups = raw.get("checkpoint_groups")
    if not isinstance(raw_groups, list) or not raw_groups:
        problems.append(f"{path}: 缺少非空的 checkpoint_groups（按区域分组的检查要点）")
    else:
        area_codes = {area.code for area in areas}
        level_codes = {level.code for level in levels}
        for g_index, group in enumerate(raw_groups):
            g_where = f"{path} checkpoint_groups[{g_index + 1}]"
            if not isinstance(group, dict):
                problems.append(f"{g_where}: 必须是映射")
                continue
            area = str(group.get("area") or "").strip()
            if not area:
                problems.append(f"{g_where}: 缺少 area（要点归属的巡检区域）")
            elif area not in area_codes:
                problems.append(f"{g_where}: 区域 {area} 未在 areas 中定义")
            items = group.get("items")
            if not isinstance(items, list) or not items:
                problems.append(f"{g_where}: 缺少非空的 items（该区域的检查要点）")
                continue
            if area and area in area_codes:
                if area in groups_covering_areas:
                    problems.append(f"{g_where}: 区域 {area} 的检查要点被重复分组")
                groups_covering_areas.add(area)
            for i_index, item in enumerate(items):
                where = f"{g_where}.items[{i_index + 1}]"
                if not isinstance(item, dict):
                    problems.append(f"{where}: 必须是映射")
                    continue
                code = str(item.get("code") or "").strip()
                text = str(item.get("text") or "").strip()
                risk = str(item.get("risk_level") or "").strip()
                if not code:
                    problems.append(f"{where}: 缺少 code")
                if not text:
                    problems.append(f"{where}: 缺少 text（检查要点内容）")
                if not risk:
                    problems.append(f"{where}: 缺少 risk_level")
                elif risk not in level_codes:
                    problems.append(f"{where}: risk_level {risk} 未在 hazard_levels 中定义")
                if code and code in seen_point_codes:
                    problems.append(f"{where}: 检查要点编码 {code} 重复")
                if code:
                    seen_point_codes.add(code)
                if code and text and risk in level_codes and area in area_codes:
                    checkpoints.append(Checkpoint(code=code, text=text, area=area, risk_level=risk))

    # 每个已声明区域都要有点，避免某区域漏配导致巡检无要点可查
    for area in areas:
        if area.code not in groups_covering_areas:
            problems.append(f"{path}: 区域「{area.code}」({area.name}) 没有配置任何检查要点分组")

    if problems:
        raise ConfigError(problems)

    content = path.read_bytes()
    import hashlib

    return SafetyConfig(
        version=int(version),
        requirements=requirements,
        hazard_levels=tuple(levels),
        areas=tuple(areas),
        checkpoints=tuple(checkpoints),
        source_path=path,
        content_hash=hashlib.sha256(content).hexdigest(),
    )


def _expected_deadline(config: SafetyConfig, level_code: str, start_iso: str) -> str:
    level = config.level(level_code)
    assert level is not None  # 已在前面校验存在
    return (date.fromisoformat(start_iso) + timedelta(days=level.default_deadline_days)).isoformat()


def load_seed(config: SafetyConfig, path: Path | None = None) -> SafetySeed:
    """读取示例数据，并校验它与当前生效的巡检要点配置完全一致。"""
    path = path or SAFETY_SEED_PATH
    raw = _read_yaml(path)
    problems: list[str] = []

    raw_records = raw.get("records")
    if raw_records is None:
        raise ConfigError(f"{path}: 缺少 records 段")
    if not isinstance(raw_records, list):
        raise ConfigError(f"{path}: records 必须是列表")

    records: list[SeedRecord] = []
    seen_numbers: set[str] = set()
    valid_status = {"待巡检", "巡检中", "待整改", "已闭合"}
    open_status = {"待整改", "巡检中"}

    for index, item in enumerate(raw_records):
        where = f"{path} records[{index + 1}]"
        if not isinstance(item, dict):
            problems.append(f"{where}: 必须是映射")
            continue
        number = str(item.get("巡检编号") or "").strip()
        area = str(item.get("区域") or "").strip()
        person = str(item.get("巡检人员") or "").strip()
        status = str(item.get("状态") or "").strip()
        if not number:
            problems.append(f"{where}: 缺少 巡检编号")
        elif number in seen_numbers:
            problems.append(f"{where}: 巡检编号 {number} 重复")
        else:
            seen_numbers.add(number)
        if not area:
            problems.append(f"{where}: 缺少 区域")
        elif config.area_name(area) is None:
            problems.append(f"{where}: 区域 {area} 未在 safetycheck.yaml 的 areas 中定义")
        if not person:
            problems.append(f"{where}: 缺少 巡检人员")
        if not status:
            problems.append(f"{where}: 缺少 状态")
        elif status not in valid_status:
            problems.append(f"{where}: 状态「{status}」非法，允许值：{'、'.join(sorted(valid_status))}")

        start = _parse_date(item.get("巡检日期"), where=f"{where} 巡检日期", problems=problems)

        points = item.get("检查要点") or []
        if not isinstance(points, list):
            problems.append(f"{where}: 检查要点 必须是编码列表")
            points = []
        point_codes: list[str] = []
        for p_index, p_code in enumerate(points):
            code = str(p_code or "").strip()
            p_where = f"{where} 检查要点[{p_index + 1}]"
            if not code:
                problems.append(f"{p_where}: 要点编码为空")
                continue
            point = config.checkpoint(code)
            if point is None:
                problems.append(f"{p_where}: 检查要点 {code} 未在 safetycheck.yaml 中定义")
            elif area and point.area != area:
                problems.append(
                    f"{p_where}: 检查要点 {code} 属于区域 {point.area}，"
                    f"与记录区域 {area} 不一致"
                )
            if code in point_codes:
                problems.append(f"{p_where}: 检查要点 {code} 在同一条记录里重复")
            point_codes.append(code)

        level_code = item.get("隐患等级")
        level_code = str(level_code).strip() if level_code is not None else None
        if level_code:
            if config.level(level_code) is None:
                problems.append(f"{where}: 隐患等级 {level_code} 未在 hazard_levels 中定义")

        deadline_iso = _parse_date(
            item.get("整改期限"), where=f"{where} 整改期限", problems=problems
        ) if item.get("整改期限") not in (None, "") else None

        hazard_text = str(item.get("发现隐患") or "").strip()
        # 存在隐患（待整改/巡检中且有隐患等级或隐患描述）时，期限与等级必须成对、且与默认天数一致
        if status in open_status and (level_code or hazard_text or deadline_iso):
            if not level_code:
                problems.append(f"{where}: 已登记隐患但缺少 隐患等级，无法确定整改期限默认天数")
            if not deadline_iso:
                problems.append(f"{where}: 已登记隐患但缺少 整改期限")
            if level_code and config.level(level_code) and start and deadline_iso:
                expected = _expected_deadline(config, level_code, start)
                if deadline_iso != expected:
                    level = config.level(level_code)
                    problems.append(
                        f"{where}: 整改期限 {deadline_iso} 与默认规则不一致，"
                        f"应为 巡检日期 {start} + {level.name}{level.default_deadline_days} 天 = {expected}"
                    )
        elif level_code and not deadline_iso and status not in open_status:
            # 已闭合的记录允许保留等级用于复盘，但不强制期限
            pass

        if number and area and person and status in valid_status and start:
            records.append(
                SeedRecord(
                    巡检编号=number,
                    区域=area,
                    巡检日期=start,
                    巡检人员=person,
                    状态=status,
                    检查要点=tuple(point_codes),
                    隐患等级=level_code,
                    发现隐患=hazard_text or None,
                    整改措施=str(item.get("整改措施") or "").strip() or None,
                    整改期限=deadline_iso,
                )
            )

    if problems:
        raise ConfigError(problems)

    import hashlib

    return SafetySeed(
        records=tuple(records),
        source_path=path,
        content_hash=hashlib.sha256(path.read_bytes()).hexdigest(),
    )

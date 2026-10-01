"""安全巡检业务规则：状态流转、字段校验与筛选口径都收在这里。

与其它模块不同，安全巡检的「巡检要点 / 巡检区域 / 隐患等级 / 整改期限默认天数」
全部来自版本化配置（:mod:`app.safetycheck`），换现场只改配置、不改这里：

- 检查要点按巡检区域分组，登记隐患时校验要点编码存在且属于该区域；
- 整改期限默认天数按隐患等级从配置读取，到期日确定性计算；
- 业务代码不内置任何具体区域、要点或天数字面量。
"""
from __future__ import annotations

from typing import Any

from app.safetycheck import deadline_for, get_safety_config
from app.safetycheck.importer import (
    F_ACTION,
    F_AREA,
    F_AREA_CODE,
    F_DATE,
    F_DEADLINE,
    F_HAZARD,
    F_LEVEL_CODE,
    F_NUMBER,
    F_PERSON,
    F_POINT_CODES,
    F_STATUS_TEXT,
)
from app.store import store

MODULE = "safetycheck"
REQUIRED_FIELDS = [F_NUMBER, F_AREA, F_DATE]
STATUS_ORDER = ["待巡检", "巡检中", "待整改", "已闭合"]
ACTION_RULES = {"开始巡检": "巡检中", "提交隐患": "待整改", "确认闭合": "已闭合"}
NEGATIVE_ACTIONS = ["提交隐患"]


def _display_row(row: dict[str, Any]) -> dict[str, Any]:
    """补一份可直接展示的视图：区域中文名、状态中文、检查要点文本都由配置解析。"""
    config = get_safety_config()
    view = dict(row)
    area_code = row.get(F_AREA_CODE)
    if area_code and config.area_name(str(area_code)):
        view[F_AREA] = config.area_name(str(area_code))
    codes = row.get(F_POINT_CODES) or []
    texts = [point.text for code in codes if (point := config.checkpoint(str(code)))]
    view["检查要点"] = "；".join(texts)
    level_code = row.get(F_LEVEL_CODE)
    if level_code:
        view["隐患等级"] = config.level_name(str(level_code))
    view[F_STATUS_TEXT] = row.get("status")
    return view


class SafetycheckService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        area: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get(F_NUMBER, ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if area:
            rows = [row for row in rows if str(row.get(F_AREA_CODE) or "") == area]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [_display_row(row) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        row = store.find(MODULE, entry_id)
        return _display_row(row) if row else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing

        config = get_safety_config()
        # 区域允许传稳定编码或中文名，统一归一到编码，跨环境结论才一致
        area_input = str(values.get(F_AREA) or "").strip()
        area_code = area_input if config.area_name(area_input) else None
        if area_code is None:
            for area in config.areas:
                if area.name == area_input:
                    area_code = area.code
                    break
        if area_code is None:
            return None, [f"巡检区域「{area_input}」不在配置区域清单内"]

        rows = store.rows(MODULE)
        entry: dict[str, Any] = {"id": store.next_id(MODULE)}
        entry[F_NUMBER] = str(values.get(F_NUMBER)).strip()
        entry[F_AREA_CODE] = area_code
        entry[F_AREA] = config.area_name(area_code)
        entry[F_DATE] = str(values.get(F_DATE)).strip()
        entry[F_PERSON] = str(values.get(F_PERSON) or "").strip() or None
        entry[F_HAZARD] = None
        entry[F_ACTION] = None
        entry[F_DEADLINE] = None
        entry[F_LEVEL_CODE] = None
        entry[F_POINT_CODES] = []
        entry["检查要点"] = ""
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        entry[F_STATUS_TEXT] = STATUS_ORDER[0]
        rows.append(entry)
        return _display_row(entry), []

    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any] | None = None
    ) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"巡检记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于安全巡检可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"

        values = values or {}

        # 提交隐患：按配置校验要点与等级，整改期限按「巡检日期 + 等级默认天数」计算
        if action == "提交隐患":
            problems = self._validate_hazard(entry, values)
            if problems:
                return None, "；".join(problems)
            config = get_safety_config()
            level_code = str(values["隐患等级"]).strip()
            point_codes = [str(code).strip() for code in values.get("检查要点", []) if str(code).strip()]
            entry[F_LEVEL_CODE] = level_code
            entry[F_POINT_CODES] = point_codes
            entry[F_HAZARD] = str(values.get(F_HAZARD) or "").strip() or None
            entry[F_ACTION] = str(values.get(F_ACTION) or "").strip() or None
            custom_deadline = str(values.get(F_DEADLINE) or "").strip()
            entry[F_DEADLINE] = custom_deadline or deadline_for(
                config, level_code, str(entry[F_DATE])
            )

        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        entry[F_STATUS_TEXT] = target
        return _display_row(entry), f"巡检记录已{action}"

    def _validate_hazard(self, entry: dict[str, Any], values: dict[str, Any]) -> list[str]:
        config = get_safety_config()
        problems: list[str] = []
        level_code = str(values.get("隐患等级") or "").strip()
        if not level_code:
            problems.append("提交隐患必须选择隐患等级，以确定整改期限默认天数")
        elif config.level(level_code) is None:
            problems.append(f"隐患等级「{level_code}」不在配置等级清单内")

        area_code = str(entry.get(F_AREA_CODE) or "")
        raw_points = values.get("检查要点") or []
        if not isinstance(raw_points, list) or not raw_points:
            problems.append("提交隐患至少勾选一个检查要点")
        else:
            for code in raw_points:
                code = str(code).strip()
                point = config.checkpoint(code)
                if point is None:
                    problems.append(f"检查要点「{code}」不在配置要点清单内")
                elif point.area != area_code:
                    problems.append(
                        f"检查要点「{point.text}」属于{config.area_name(point.area)}，"
                        f"不能登记到{config.area_name(area_code)}的巡检记录"
                    )
        return problems

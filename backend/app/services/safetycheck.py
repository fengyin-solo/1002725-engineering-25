"""安全巡检业务规则：状态流转、字段校验与筛选口径都收在这里。

区域、巡检要点、隐患等级与整改期限天数全部来自配置（app/inspection.py 加载的
``config/safetycheck.json``），本模块不写死任何一项：换现场只改配置文件，
不用动业务代码。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.inspection import STATUS_ORDER, compute_deadline
from app.store import store

MODULE = "safetycheck"
REQUIRED_FIELDS = ["巡检编号", "巡检区域", "巡检要点", "巡检日期"]
ACTION_RULES = {"开始巡检": "巡检中", "提交隐患": "待整改", "确认闭合": "已闭合"}
NEGATIVE_ACTIONS = []


class SafetycheckService:
    """安全巡检服务。配置由 store 在启动时加载并校验，运行期直接只读使用。"""

    def _config(self):
        config = store.safety_config
        if config is None:
            # 理论上到不了：store 初始化时已校验并加载，缺项会直接终止启动。
            raise RuntimeError("安全巡检配置尚未加载，请检查 config/safetycheck.json")
        return config

    def config_view(self) -> dict[str, Any]:
        """配置查询接口：区域要点分组 + 等级天数，前端下拉直接用这份数据。"""
        return self._config().to_dict()

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        area: str | None = None,
        risk_level: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("巡检编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if area:
            rows = [row for row in rows if row.get("巡检区域") == area]
        if risk_level:
            rows = [row for row in rows if row.get("隐患等级") == risk_level]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing

        config = self._config()
        errors: list[str] = []
        area_name = str(values["巡检区域"]).strip()
        point_name = str(values["巡检要点"]).strip()
        area = config.area_by_name.get(area_name)
        if area is None:
            errors.append(f"巡检区域「{area_name}」不在配置中")
        elif config.checkpoint_by_key.get((area_name, point_name)) is None:
            errors.append(f"巡检要点「{point_name}」不属于配置中的巡检区域「{area_name}」")

        # 发现隐患时必须给等级与发现日期；整改期限由配置天数确定性算出，不接受手工猜测。
        found_desc = str(values.get("发现隐患") or "").strip()
        risk_name = str(values.get("隐患等级") or "").strip() or None
        found_raw = str(values.get("发现日期") or values.get("巡检日期") or "").strip()
        found_on: date | None = None
        deadline: str | None = None
        if found_desc:
            if not risk_name:
                errors.append("登记隐患时必须选择隐患等级")
            elif risk_name not in config.risk_by_name:
                errors.append(f"隐患等级「{risk_name}」不在配置中")
            try:
                found_on = date.fromisoformat(found_raw)
            except ValueError:
                errors.append("发现日期不是合法日期（应为 YYYY-MM-DD）")
            if risk_name in config.risk_by_name and found_on is not None:
                deadline = compute_deadline(
                    found_on, config.risk_by_name[risk_name].deadline_days
                ).isoformat()
        if errors:
            return None, errors

        rows = store.rows(MODULE)
        if any(str(row.get("巡检编号")) == str(values["巡检编号"]).strip() for row in rows):
            return None, [f"巡检编号「{values['巡检编号']}」已存在，重复导入不会覆盖已有记录"]

        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        status = STATUS_ORDER[0]
        entry.update({
            "status": status,
            "pending": True,
            "abnormal": False,
            "巡检编号": str(values["巡检编号"]).strip(),
            "巡检区域": area_name,
            "巡检要点": point_name,
            "隐患等级": risk_name,
            "巡检日期": str(values["巡检日期"]).strip(),
            "巡检人员": str(values.get("巡检人员") or "").strip(),
            "发现隐患": found_desc,
            "整改措施": str(values.get("整改措施") or "").strip(),
            "发现日期": found_on.isoformat() if found_on else None,
            "整改期限": deadline,
            "巡检状态": status,
        })
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"巡检记录 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于安全巡检可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["巡检状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS or target == "待整改"
        return entry, f"巡检记录已{action}"

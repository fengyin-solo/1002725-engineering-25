"""安全巡检接口：维护巡检记录，覆盖开始巡检、提交隐患、确认闭合等动作。

巡检要点、区域、隐患等级由配置驱动，前端通过 ``/config`` 拉取，不在前后端硬编码。
``/config/reload`` 用于换现场更新配置后重新校验并幂等生效，不会覆盖已有巡检记录。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.safetycheck import bootstrap, get_safety_config
from app.safetycheck.loader import ConfigError
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.safetycheck import SafetycheckService

router = APIRouter(prefix="/api/safetycheck", tags=["安全巡检"])

service = SafetycheckService()

LIST_FIELDS = ["巡检编号", "巡检区域", "巡检日期", "巡检人员", "发现隐患", "整改措施", "整改期限", "巡检状态"]
STATUSES = ["待巡检", "巡检中", "待整改", "已闭合"]


@router.get("/config")
def get_config() -> dict[str, Any]:
    """返回当前生效的巡检配置：按区域分组的检查要点、隐患等级与默认整改天数。"""
    config = get_safety_config()
    return {
        "version": config.version,
        "config_hash": config.content_hash,
        "hazard_levels": [
            {"code": level.code, "name": level.name, "default_deadline_days": level.default_deadline_days}
            for level in config.hazard_levels
        ],
        "areas": [{"code": area.code, "name": area.name} for area in config.areas],
        "checkpoint_groups": [
            {
                "area": area.code,
                "area_name": area.name,
                "items": [
                    {"code": point.code, "text": point.text, "risk_level": point.risk_level}
                    for point in config.checkpoints_by_area(area.code)
                ],
            }
            for area in config.areas
        ],
    }


@router.post("/config/reload")
def reload_config() -> dict[str, Any]:
    """重新读取并校验配置；同一份配置重复导入只生效一次，且不覆盖已有巡检记录。"""
    try:
        report = bootstrap(force=True)
    except ConfigError as exc:
        raise HTTPException(status_code=500, detail=f"配置校验未通过，已保持原配置：{exc}")
    return report.as_dict()


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按巡检编号检索"),
    status: str | None = Query(default=None, description="待巡检、巡检中、待整改、已闭合"),
    area: str | None = Query(default=None, description="巡检区域编码，来自 /config"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按巡检编号、状态与区域过滤安全巡检列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, area=area, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出安全巡检清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "safetycheck", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条巡检记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"巡检记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条巡检记录，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少或非法字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="巡检记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条巡检记录执行开始巡检、提交隐患、确认闭合；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)

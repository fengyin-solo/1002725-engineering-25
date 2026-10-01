"""安全巡检接口：维护巡检记录，覆盖开始巡检、提交隐患、确认闭合等动作。

巡检要点与隐患等级不写在代码里，统一来自配置文件，配置查询接口直接把
启动时校验通过的配置透出给前端。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.safetycheck import SafetycheckService

router = APIRouter(prefix="/api/safetycheck", tags=["安全巡检"])

service = SafetycheckService()

LIST_FIELDS = [
    "巡检编号", "巡检区域", "巡检要点", "隐患等级", "巡检日期", "巡检人员",
    "发现隐患", "整改措施", "发现日期", "整改期限", "巡检状态",
]
STATUSES = ["待巡检", "巡检中", "待整改", "已闭合"]


@router.get("/config")
def get_config() -> dict[str, Any]:
    """返回当前生效的巡检要点（按区域分组）与隐患等级整改天数。"""
    return service.config_view()


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出安全巡检清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "safetycheck", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按巡检编号检索"),
    status: str | None = Query(default=None, description="待巡检、巡检中、待整改、已闭合"),
    area: str | None = Query(default=None, description="按配置中的巡检区域过滤"),
    risk_level: str | None = Query(default=None, description="按配置中的隐患等级过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按巡检编号、状态、区域、隐患等级过滤安全巡检列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(
        keyword=keyword, status=status, area=area, risk_level=risk_level, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条巡检记录明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"巡检记录 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条巡检记录，缺字段或与配置对不上时说明原因而不是静默丢弃。"""
    entry, problems = service.create_entry(payload.values)
    if problems:
        return ActionResult(ok=False, message="；".join(problems))
    return ActionResult(ok=True, message="巡检记录已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条巡检记录执行开始巡检、提交隐患、确认闭合；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)

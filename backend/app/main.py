"""港口集装箱作业管理平台 后端服务入口。

启动：uvicorn app.main:app --host 127.0.0.1 --port 8000
健康检查：GET /api/health

安全巡检的配置与示例数据在 store 初始化（import 本模块）时完成校验和幂等导入；
若配置缺失或有缺项，import 阶段就会抛 InspectionConfigError，服务无法启动，
错误消息会指出缺的是哪一项。
"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import ROUTERS
from app.store import store

logger = logging.getLogger("app.bootstrap")

app = FastAPI(title="港口集装箱作业管理平台", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in ROUTERS:
    app.include_router(module.router)

if store.safety_report is not None:
    logger.info(
        "安全巡检配置已就绪：区域 %s 个、要点 %s 条、等级 %s 个；"
        "示例记录新增 %s 条、按编号幂等跳过 %s 条",
        store.safety_report.areas,
        store.safety_report.checkpoints,
        store.safety_report.risk_levels,
        store.safety_report.inserted,
        store.safety_report.skipped,
    )


@app.get("/api/health")
def health() -> dict[str, object]:
    """健康检查：确认服务已经监听、示例数据已经就绪。"""
    report = store.safety_report
    return {
        "ok": True,
        "app": settings.app_name,
        "modules": len(store.module_names()),
        "safety_config": {
            "areas": report.areas if report else 0,
            "checkpoints": report.checkpoints if report else 0,
            "risk_levels": report.risk_levels if report else 0,
            "seed_inserted": report.inserted if report else 0,
            "seed_skipped": report.skipped if report else 0,
        },
    }


@app.get("/api/overview")
def overview() -> dict[str, object]:
    """运营概览：把各业务模块的待处理量汇总成看板卡片。"""
    return store.overview()

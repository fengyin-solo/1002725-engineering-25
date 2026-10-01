"""港口集装箱作业管理平台 后端服务入口。

启动：uvicorn app.main:app --host 127.0.0.1 --port 8000
健康检查：GET /api/health

启动时会先校验安全巡检的依赖与配置是否齐全（见 app/safetycheck），缺项直接抛错中止，
不会带着不完整的配置起来。
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.routers import ROUTERS
from app.safetycheck import bootstrap
from app.safetycheck.loader import ConfigError
from app.store import store

logger = logging.getLogger("app.startup")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动即校验依赖、巡检要点与示例数据；任一缺项都中断启动并指出缺哪一个。
    try:
        report = bootstrap()
    except ConfigError as exc:
        logger.error("安全巡检配置校验未通过，服务拒绝启动：%s", exc)
        raise
    logger.info(
        "安全巡检配置已就绪 config_hash=%s 新增示例记录=%s 跳过既有记录=%s",
        report.config_hash[:12],
        report.imported_records,
        report.skipped_existing_records,
    )
    yield


app = FastAPI(title="港口集装箱作业管理平台", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for module in ROUTERS:
    app.include_router(module.router)


@app.get("/api/health")
def health() -> dict[str, object]:
    """健康检查：确认服务已经监听、示例数据已经就绪。"""
    return {"ok": True, "app": settings.app_name, "modules": len(store.module_names())}


@app.get("/api/overview")
def overview() -> dict[str, object]:
    """运营概览：把各业务模块的待处理量汇总成看板卡片。"""
    return store.overview()

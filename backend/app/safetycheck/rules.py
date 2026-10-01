"""整改期限规则：默认天数只来自配置，到期日确定性计算。

把日期计算单独放一处，业务代码与示例数据校验共用同一口径，
避免「同一个隐患等级在各处默认天数不一样」。
"""
from __future__ import annotations

from datetime import date, timedelta

from .loader import SafetyConfig


def deadline_for(config: SafetyConfig, level_code: str, start: str | date) -> str:
    """按「起始日期 + 隐患等级默认天数」返回 YYYY-MM-DD 到期日。

    起始日期可以是 ``YYYY-MM-DD`` 字符串或 :class:`datetime.date`。
    等级不存在时抛 KeyError——调用方应先用启动校验保证配置齐全。
    """
    level = config.level(level_code)
    if level is None:
        raise KeyError(f"隐患等级 {level_code} 未在配置中定义")
    start_date = date.fromisoformat(start) if isinstance(start, str) else start
    return (start_date + timedelta(days=level.default_deadline_days)).isoformat()

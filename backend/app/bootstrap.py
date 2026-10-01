"""命令行入口：手动重新导入安全巡检配置与示例数据。

用法（在 backend/ 目录下）：

    .venv/bin/python -m app.bootstrap

配置文件路径可用 --config / --seed 覆盖，也可用环境变量
SAFETY_CONFIG_DIR 整体换目录（换现场时指向新现场的配置目录）。

语义与启动引导完全一致：

- 导入前先校验，配置或示例数据有缺项直接非零退出，错误消息点名缺哪一项；
- 示例数据按巡检编号幂等导入：同一份配置重复导入只生效一次，
  已经存在的巡检记录（含运行期新建、改过状态的）不会被覆盖；
- 巡检要点、隐患等级配置在通过校验后整体生效。
"""
from __future__ import annotations

import argparse
import sys

from app.inspection import InspectionConfigError
from app import store as store_module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="重新导入安全巡检配置与示例数据（幂等）")
    parser.add_argument("--config", type=str, default=None, help="safetycheck.json 路径")
    parser.add_argument("--seed", type=str, default=None, help="safetycheck.seed.json 路径")
    args = parser.parse_args(argv)

    try:
        instance = store_module.bootstrap(
            config_path=args.config,
            seed_path=args.seed,
        )
    except InspectionConfigError as exc:
        print(f"[安全巡检配置] 导入被拒绝：{exc}", file=sys.stderr)
        return 2

    # 校验通过的实例设为全局单例，后续在同一进程内通过 app.store.store 访问。
    store_module.set_store(instance)
    report = instance.safety_report
    assert report is not None

    print(
        "[安全巡检配置] 导入完成："
        f"区域 {report.areas} 个、巡检要点 {report.checkpoints} 条、"
        f"隐患等级 {report.risk_levels} 个；"
        f"示例记录新增 {report.inserted} 条，"
        f"因已存在跳过 {report.skipped} 条"
        + (f"（跳过：{'、'.join(report.skipped_ids)}）" if report.skipped_ids else "（跳过：无）")
    )
    if report.inserted == 0:
        print("[安全巡检配置] 同一份配置重复导入只生效一次，已有巡检记录未被覆盖。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

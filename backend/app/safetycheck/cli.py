"""命令行：校验安全巡检配置并幂等初始化示例数据。

用途：
- 部署流水线在启动前先 ``python -m app.safetycheck.cli validate``，配置缺项会以非零码失败；
- 手工排查时 ``python -m app.safetycheck.cli import`` 可查看幂等导入结果。

退出码：0 通过；1 配置或依赖校验未通过（错误信息逐项指出缺哪一个）。
"""
from __future__ import annotations

import argparse
import sys

from .loader import ConfigError, load_config, load_seed
from .registry import bootstrap, reset_for_tests


def _validate() -> int:
    try:
        config = load_config()
        seed = load_seed(config)
    except ConfigError as exc:
        print("安全巡检配置校验未通过：", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("配置校验通过：")
    print(f"  配置文件   : {config.source_path}")
    print(f"  配置指纹   : {config.content_hash}")
    print(f"  隐患等级   : {len(config.hazard_levels)} 个")
    print(f"  巡检区域   : {len(config.areas)} 个")
    print(f"  检查要点   : {len(config.checkpoints)} 条")
    print(f"  示例数据   : {seed.source_path}（{len(seed.records)} 条记录，指纹 {seed.content_hash[:12]}）")
    return 0


def _import() -> int:
    code = _validate()
    if code != 0:
        return code
    reset_for_tests()
    report = bootstrap()
    print("导入结果：")
    print(f"  changed                 : {report.changed}")
    print(f"  新补登记示例记录        : {report.imported_records}")
    print(f"  跳过（已存在未覆盖）    : {report.skipped_existing_records}")
    for note in report.notes:
        print(f"  - {note}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="安全巡检配置校验与幂等初始化")
    parser.add_argument("command", choices=["validate", "import"], help="validate 仅校验；import 校验并幂等初始化")
    args = parser.parse_args(argv)
    return _validate() if args.command == "validate" else _import()


if __name__ == "__main__":
    raise SystemExit(main())

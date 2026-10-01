"""安全巡检配置体系的测试。

只依赖标准库 unittest，直接用 .venv/bin/python -m unittest discover backend/tests 运行。
覆盖：配置校验、示例数据一致性、确定性期限、幂等导入不覆盖、跨环境结论相同。
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

from app.inspection import (  # noqa: E402
    InspectionConfigError,
    compute_deadline,
    import_seed_records,
    load_and_validate,
    parse_config,
    validate_seed_records,
)

CONFIG_DIR = BACKEND / "config"


def _load_json(name: str):
    return json.loads((CONFIG_DIR / name).read_text(encoding="utf-8"))


class ConfigValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = _load_json("safetycheck.json")
        self.seed = _load_json("safetycheck.seed.json")

    def test_versioned_config_loads(self) -> None:
        config = parse_config(copy.deepcopy(self.config))
        self.assertEqual(config.schema_version, 1)
        self.assertTrue(config.areas)
        self.assertTrue(config.risk_levels)
        self.assertEqual(
            sum(len(a.checkpoints) for a in config.areas), 12
        )

    def test_missing_deadline_days_is_named(self) -> None:
        cfg = copy.deepcopy(self.config)
        del cfg["risk_levels"][0]["deadline_days"]
        with self.assertRaisesRegex(InspectionConfigError, "缺少必填项「deadline_days」"):
            parse_config(cfg)

    def test_checkpoint_referencing_unknown_level_is_named(self) -> None:
        cfg = copy.deepcopy(self.config)
        cfg["areas"][0]["checkpoints"][0]["risk_level"] = "特大"
        with self.assertRaisesRegex(InspectionConfigError, "「特大」未在 risk_levels 中配置"):
            parse_config(cfg)

    def test_empty_config_is_rejected(self) -> None:
        with self.assertRaisesRegex(InspectionConfigError, "areas"):
            parse_config({"areas": [], "risk_levels": []})

    def test_missing_config_file_is_named(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.json"
            seed = Path(tmp) / "safetycheck.seed.json"
            seed.write_text(json.dumps(self.seed, ensure_ascii=False), encoding="utf-8")
            with self.assertRaisesRegex(InspectionConfigError, "安全巡检配置缺失"):
                load_and_validate(missing, seed)

    def test_duplicate_codes_are_rejected(self) -> None:
        cfg = copy.deepcopy(self.config)
        cfg["risk_levels"][1]["code"] = cfg["risk_levels"][0]["code"]
        with self.assertRaisesRegex(InspectionConfigError, "隐患等级编码重复"):
            parse_config(cfg)


class SeedConsistencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config_raw = _load_json("safetycheck.json")
        self.seed_raw = _load_json("safetycheck.seed.json")
        self.config = parse_config(copy.deepcopy(self.config_raw))

    def test_committed_seed_matches_committed_checkpoints(self) -> None:
        """入库的示例数据必须与启动时读到的巡检要点一致，否则启动失败。"""
        normalized = validate_seed_records(copy.deepcopy(self.seed_raw["records"]), self.config)
        self.assertEqual(len(normalized), 4)
        # 留空的整改期限按配置补算，不留空的维持原值。
        by_id = {row["巡检编号"]: row for row in normalized}
        self.assertEqual(by_id["SAFE-0003"]["整改期限"], "2026-09-10")  # 较大 7 天
        self.assertEqual(by_id["SAFE-0002"]["整改期限"], "2026-09-05")  # 重大 3 天

    def test_unknown_area_in_seed_is_named(self) -> None:
        records = copy.deepcopy(self.seed_raw["records"])
        records[0]["巡检区域"] = "油码头"
        with self.assertRaisesRegex(InspectionConfigError, "「油码头」未在配置中定义"):
            validate_seed_records(records, self.config)

    def test_point_not_belonging_to_area_is_named(self) -> None:
        records = copy.deepcopy(self.seed_raw["records"])
        records[0]["巡检要点"] = records[2]["巡检要点"]
        with self.assertRaisesRegex(InspectionConfigError, "不属于配置中的巡检区域"):
            validate_seed_records(records, self.config)

    def test_wrong_deadline_in_seed_is_named_with_expected_value(self) -> None:
        records = copy.deepcopy(self.seed_raw["records"])
        records[1]["整改期限"] = "2026-12-31"
        with self.assertRaisesRegex(InspectionConfigError, "应为 2026-09-05"):
            validate_seed_records(records, self.config)

    def test_missing_field_in_seed_is_named(self) -> None:
        records = copy.deepcopy(self.seed_raw["records"])
        del records[0]["巡检人员"]
        with self.assertRaisesRegex(InspectionConfigError, "缺少必填项「巡检人员」"):
            validate_seed_records(records, self.config)

    def test_duplicate_seed_ids_are_rejected(self) -> None:
        records = copy.deepcopy(self.seed_raw["records"])
        records[1]["巡检编号"] = records[0]["巡检编号"]
        with self.assertRaisesRegex(InspectionConfigError, "巡检编号重复：SAFE-0001"):
            validate_seed_records(records, self.config)

    def test_hazard_requires_level_and_found_date(self) -> None:
        records = copy.deepcopy(self.seed_raw["records"])
        records[1]["隐患等级"] = None
        records[1]["发现日期"] = None
        with self.assertRaises(InspectionConfigError) as ctx:
            validate_seed_records(records, self.config)
        message = str(ctx.exception)
        self.assertIn("缺少必填项「隐患等级」", message)
        self.assertIn("缺少必填项「发现日期」", message)


class DeadlineDeterminismTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config_raw = _load_json("safetycheck.json")

    def test_deadline_is_pure_date_math(self) -> None:
        # 不读系统时钟：同一天在任何环境、任何时区跑结果一致。
        self.assertEqual(compute_deadline(date(2026, 9, 2), 3), date(2026, 9, 5))
        self.assertEqual(compute_deadline(date(2026, 9, 3), 7), date(2026, 9, 10))
        self.assertEqual(compute_deadline(date(2026, 8, 20), 15), date(2026, 9, 4))

    def test_same_config_produces_same_conclusion_in_two_runs(self) -> None:
        """模拟两个环境：各自独立加载同一份入库配置与示例数据，结论必须完全相同。"""
        outcomes = []
        for _ in range(2):
            config = parse_config(copy.deepcopy(self.config_raw))
            seed = _load_json("safetycheck.seed.json")["records"]
            normalized = validate_seed_records(copy.deepcopy(seed), config)
            rows: list[dict] = []
            import_seed_records(rows, normalized, config)
            outcomes.append([
                (r["巡检编号"], r["巡检区域"], r["巡检要点"], r["隐患等级"], r["整改期限"], r["status"])
                for r in rows
            ])
        self.assertEqual(outcomes[0], outcomes[1])
        self.assertEqual(len(outcomes[0]), 4)


class IdempotentImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = parse_config(_load_json("safetycheck.json"))
        records = _load_json("safetycheck.seed.json")["records"]
        self.normalized = validate_seed_records(records, self.config)

    def test_second_import_inserts_nothing(self) -> None:
        rows: list[dict] = []
        first = import_seed_records(rows, self.normalized, self.config)
        second = import_seed_records(rows, self.normalized, self.config)
        self.assertEqual(first.inserted, 4)
        self.assertEqual(first.skipped, 0)
        self.assertEqual(second.inserted, 0)
        self.assertEqual(second.skipped, 4)
        self.assertEqual(len(rows), 4)

    def test_reimport_does_not_overwrite_existing_records(self) -> None:
        rows: list[dict] = []
        import_seed_records(rows, self.normalized, self.config)
        # 模拟运行期已有的巡检记录被改过：状态流转、现场手改了措施。
        rows[0]["status"] = "已闭合"
        rows[0]["巡检状态"] = "已闭合"
        rows[0]["整改措施"] = "运行期新增的整改说明"
        snapshot = copy.deepcopy(rows)

        report = import_seed_records(rows, self.normalized, self.config)
        self.assertEqual(report.inserted, 0)
        self.assertEqual(rows, snapshot, "重复导入覆盖了已有巡检记录")

    def test_partial_new_records_are_added_without_touching_existing(self) -> None:
        rows: list[dict] = []
        import_seed_records(rows, self.normalized[:2], self.config)
        report = import_seed_records(rows, self.normalized, self.config)
        self.assertEqual(report.inserted, 2)
        self.assertEqual(report.skipped, 2)
        self.assertEqual(len(rows), 4)
        self.assertEqual([r["巡检编号"] for r in rows],
                         ["SAFE-0001", "SAFE-0002", "SAFE-0003", "SAFE-0004"])

    def test_new_record_id_continues_after_existing_max(self) -> None:
        rows: list[dict] = [{"id": 99, "巡检编号": "SAFE-9001"}]
        report = import_seed_records(rows, self.normalized[:1], self.config)
        self.assertEqual(report.inserted, 1)
        self.assertEqual(rows[-1]["id"], 100)


class StoreBootstrapTests(unittest.TestCase):
    def test_store_bootstraps_from_committed_files(self) -> None:
        # 延迟导入：store 是模块级单例，导入即完成一次引导。
        from app.store import store

        rows = store.rows("safetycheck")
        self.assertEqual(len(rows), 4)
        self.assertIsNotNone(store.safety_config)
        self.assertEqual(store.safety_report.inserted, 4)
        # 再导一次只生效一次。
        again = store.bootstrap_safety()
        self.assertEqual(again.inserted, 0)
        self.assertEqual(again.skipped, 4)
        self.assertEqual(len(store.rows("safetycheck")), 4)


if __name__ == "__main__":
    unittest.main()

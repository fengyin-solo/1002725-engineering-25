"""安全巡检配置化需求的回归测试。

覆盖需求要点：
- 检查要点按区域分组、整改期限按隐患等级配置；
- 启动校验依赖与配置齐全，缺项逐项报错指出缺哪一个；
- 同一份配置重复导入只生效一次（内容哈希幂等）；
- 重复导入不覆盖已有巡检记录；
- 示例数据与启动读到的巡检要点一致，期限与默认天数一致；
- 同一份配置在两个环境的初始结论确定一致；
- 提交隐患时期限按「巡检日期 + 等级默认天数」确定性计算，并校验要点归属区域。
"""
from __future__ import annotations

import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from app.safetycheck import bootstrap, deadline_for, get_safety_config, reset_for_tests
from app.safetycheck.importer import MODULE
from app.safetycheck.loader import (
    ConfigError,
    load_config,
    load_seed,
    verify_dependencies,
)
from app.store import store

from conftest import SafetycheckTestCase

CONFIG_PATH = Path(__file__).resolve().parent.parent / "app" / "config_data" / "safetycheck.yaml"
SEED_PATH = CONFIG_PATH.parent / "safetycheck.seed.yaml"


def _httpx_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("httpx") is not None


class ConfigLoadingTests(SafetycheckTestCase):
    def test_loads_grouped_checkpoints_and_levels(self) -> None:
        config = load_config()
        self.assertEqual({a.code for a in config.areas}, {"apron", "yard", "gate", "warehouse"})
        self.assertEqual(
            {level.code: level.default_deadline_days for level in config.hazard_levels},
            {"major": 1, "serious": 3, "general": 7, "minor": 15},
        )
        # 检查要点按区域分组，且每条要点都能归到一个已声明区域与等级
        for point in config.checkpoints:
            self.assertIn(point.area, config.area_codes)
            self.assertIn(point.risk_level, config.level_codes)
        self.assertTrue(len(config.checkpoints) >= 8)
        self.assertEqual(len(config.checkpoints_by_area("apron")), 3)

    def test_shipped_config_and_seed_pass_validation(self) -> None:
        config = load_config(CONFIG_PATH)
        seed = load_seed(config, SEED_PATH)
        self.assertTrue(seed.records)

    def test_missing_file_is_reported(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            load_config(Path(tempfile.gettempdir()) / "absent-safetycheck.yaml")
        self.assertTrue(any("缺少配置文件" in p for p in ctx.exception.problems))

    def test_missing_level_section_collects_problems(self) -> None:
        raw = CONFIG_PATH.read_text(encoding="utf-8").replace("hazard_levels:", "hazard_levels_x:")
        self._assert_problem(raw, "缺少非空的 hazard_levels")

    def test_area_without_checkpoint_group_is_reported(self) -> None:
        text = CONFIG_PATH.read_text(encoding="utf-8")
        head, marker, _tail = text.partition("  - area: warehouse")
        self.assertTrue(marker)
        bad = head.rstrip() + "\n"
        self._assert_problem(bad, "没有配置任何检查要点分组")

    def test_duplicate_area_code_and_unknown_level_are_reported(self) -> None:
        bad = (
            CONFIG_PATH.read_text(encoding="utf-8")
            .replace("  - code: gate\n", "  - code: yard\n", 1)
            .replace("risk_level: minor", "risk_level: ghost", 1)
        )
        with self.assertRaises(ConfigError) as ctx:
            load_config(_write(bad))
        joined = "\n".join(ctx.exception.problems)
        self.assertIn("区域编码 yard 重复", joined)
        self.assertIn("risk_level ghost 未在 hazard_levels", joined)

    def test_missing_dependency_is_reported(self) -> None:
        raw = {
            "requires": [
                {
                    "name": "假依赖",
                    "import_name": "definitely_missing_pkg_xyz",
                    "install": "pip install fake",
                    "purpose": "测试",
                }
            ]
        }
        with self.assertRaises(ConfigError) as ctx:
            verify_dependencies(raw, where=Path("safetycheck.yaml"))
        self.assertIn("缺少依赖「假依赖」", ctx.exception.problems[0])
        self.assertIn("pip install fake", ctx.exception.problems[0])

    def _assert_problem(self, config_text: str, fragment: str) -> None:
        with self.assertRaises(ConfigError) as ctx:
            load_config(_write(config_text))
        self.assertTrue(
            any(fragment in p for p in ctx.exception.problems),
            f"期望报错包含 {fragment!r}，实际：{ctx.exception.problems}",
        )


def _write(text: str) -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8")
    handle.write(text)
    handle.close()
    return Path(handle.name)


class SeedConsistencyTests(SafetycheckTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.config = load_config(CONFIG_PATH)

    def _seed(self, text: str) -> None:
        path = _write(text)
        load_seed(self.config, path)

    def test_unknown_checkpoint_rejected(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            self._seed(_one_record(points="[nope-99]", deadline="2026-09-02"))
        self.assertIn("检查要点 nope-99 未在 safetycheck.yaml 中定义", ctx.exception.problems[0])

    def test_checkpoint_from_other_area_rejected(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            self._seed(_one_record(area="apron", points="[gate-02]", level="minor", deadline="2026-09-16"))
        self.assertIn("与记录区域 apron 不一致", ctx.exception.problems[0])

    def test_deadline_must_match_default_days(self) -> None:
        # general=7 天，2026-09-01 应得 2026-09-08，故意写成 2026-09-10
        with self.assertRaises(ConfigError) as ctx:
            self._seed(_one_record(area="gate", points="[gate-01]", level="general", deadline="2026-09-10"))
        message = ctx.exception.problems[0]
        self.assertIn("与默认规则不一致", message)
        self.assertIn("2026-09-08", message)

    def test_hazard_requires_level_and_deadline(self) -> None:
        text = _one_record(area="gate", points="[gate-01]", level=None, deadline="2026-09-10")
        with self.assertRaises(ConfigError) as ctx:
            self._seed(text)
        self.assertTrue(any("缺少 隐患等级" in p for p in ctx.exception.problems))


def _one_record(*, area: str = "apron", points: str, level: str | None = "major",
                deadline: str = "2026-09-02") -> str:
    level_line = f"  隐患等级: {level}\n" if level else ""
    return (
        "records:\n"
        "- 巡检编号: X1\n"
        f"  区域: {area}\n"
        '  巡检日期: "2026-09-01"\n'
        "  巡检人员: 甲\n"
        "  状态: 待整改\n"
        f"  检查要点: {points}\n"
        f"{level_line}"
        "  发现隐患: 隐患描述\n"
        "  整改措施: 整改描述\n"
        f'  整改期限: "{deadline}"\n'
    )


class DeadlineRuleTests(SafetycheckTestCase):
    def test_deadline_adds_configured_days_deterministically(self) -> None:
        config = load_config(CONFIG_PATH)
        self.assertEqual(deadline_for(config, "major", "2026-10-01"), "2026-10-02")
        self.assertEqual(deadline_for(config, "serious", "2026-10-01"), "2026-10-04")
        self.assertEqual(deadline_for(config, "general", "2026-10-01"), "2026-10-08")
        self.assertEqual(deadline_for(config, "minor", "2026-10-01"), "2026-10-16")


class IdempotentImportTests(SafetycheckTestCase):
    def test_bootstrap_seeds_records_once(self) -> None:
        report1 = bootstrap()
        self.assertTrue(report1.changed)
        self.assertEqual(report1.imported_records, 3)
        # 再引导一次：同一份配置只生效一次，不新增
        report2 = bootstrap()
        self.assertFalse(report2.changed)
        self.assertEqual(len(store.rows(MODULE)), 3)

    def test_reimport_does_not_overwrite_existing_records(self) -> None:
        bootstrap()
        rows = store.rows(MODULE)
        # 模拟现场已有的一条运行期记录，并对其做状态流转
        rows.append({
            "id": store.next_id(MODULE), "status": "待整改", "pending": True, "abnormal": True,
            "巡检编号": "SAFE-LIVE", "巡检区域": "危品仓库与冷链区",
            "巡检日期": "2026-10-01", "巡检人员": "现场员",
            "发现隐患": "运行期隐患", "整改措施": "运行期措施", "整改期限": "2026-10-02",
            "巡检状态": "待整改", "_area_code": "warehouse", "_hazard_level": "major",
            "_checkpoint_codes": ["warehouse-01"],
        })
        # 修改配置内容（哈希变化）后强制 reload，已有记录也必须原样保留
        config = load_config(CONFIG_PATH)
        report = bootstrap(force=True)
        live = store.find_by_key(MODULE, "巡检编号", "SAFE-LIVE")
        self.assertIsNotNone(live)
        self.assertEqual(live["发现隐患"], "运行期隐患")
        self.assertEqual(live["status"], "待整改")
        # 三条示例编号已存在，全部跳过未覆盖
        self.assertEqual(report.skipped_existing_records, 3)
        self.assertEqual(report.imported_records, 0)

    def test_two_environments_produce_identical_initial_state(self) -> None:
        # 环境一
        reset_for_tests(); store.clear(MODULE)
        bootstrap()
        fingerprint_a = self._fingerprint()
        # 环境二（同一进程内等价重建：清空后重新引导同一份配置）
        reset_for_tests(); store.clear(MODULE)
        bootstrap()
        fingerprint_b = self._fingerprint()
        self.assertEqual(fingerprint_a, fingerprint_b)

    def _fingerprint(self) -> str:
        rows = [dict(row) for row in store.rows(MODULE)]
        canon = json.dumps(rows, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(canon.encode()).hexdigest()


class ServiceConfigDrivenTests(SafetycheckTestCase):
    def setUp(self) -> None:
        super().setUp()
        bootstrap()
        from app.services.safetycheck import SafetycheckService
        self.service = SafetycheckService()

    def test_create_normalizes_area_name_from_code(self) -> None:
        entry, missing = self.service.create_entry(
            {"巡检编号": "SAFE-S1", "巡检区域": "apron", "巡检日期": "2026-10-01", "巡检人员": "甲"}
        )
        self.assertEqual(missing, [])
        self.assertEqual(entry["巡检区域"], "码头前沿作业区")

    def test_create_rejects_unknown_area(self) -> None:
        _, missing = self.service.create_entry(
            {"巡检编号": "SAFE-S2", "巡检区域": "不存在区域", "巡检日期": "2026-10-01"}
        )
        self.assertTrue(any("不在配置区域清单内" in m for m in missing))

    def test_submit_hazard_sets_deadline_from_level(self) -> None:
        entry, _ = self.service.create_entry(
            {"巡检编号": "SAFE-S3", "巡检区域": "apron", "巡检日期": "2026-10-01"}
        )
        self.service.run_action(entry["id"], "开始巡检", {})
        result, message = self.service.run_action(
            entry["id"], "提交隐患", {"隐患等级": "general", "检查要点": ["apron-03"], "发现隐患": "x"}
        )
        self.assertIsNotNone(result, message)
        self.assertEqual(result["整改期限"], "2026-10-08")
        self.assertEqual(result["隐患等级"], "一般隐患")

    def test_submit_hazard_rejects_cross_area_checkpoint(self) -> None:
        entry, _ = self.service.create_entry(
            {"巡检编号": "SAFE-S4", "巡检区域": "apron", "巡检日期": "2026-10-01"}
        )
        result, message = self.service.run_action(
            entry["id"], "提交隐患", {"隐患等级": "minor", "检查要点": ["gate-02"]}
        )
        self.assertIsNone(result)
        self.assertIn("不能登记到", message)

    def test_list_filter_by_area_code(self) -> None:
        items, total = self.service.list_entries(area="yard")
        self.assertTrue(all(row["_area_code"] == "yard" for row in items))
        self.assertGreaterEqual(total, 1)


@unittest.skipUnless(_httpx_available(), "需要 httpx 才能跑 FastAPI TestClient")
class ApiTests(SafetycheckTestCase):
    def test_http_flow_and_reload_idempotency(self) -> None:
        from fastapi.testclient import TestClient
        from app.main import app

        with TestClient(app) as client:  # 触发 lifespan 启动校验
            self.assertEqual(client.get("/api/health").json()["modules"], 20)
            cfg = client.get("/api/safetycheck/config").json()
            self.assertEqual(len(cfg["checkpoint_groups"]), 4)

            created = client.post("/api/safetycheck", json={
                "values": {"巡检编号": "SAFE-HTTP", "巡检区域": "gate", "巡检日期": "2026-10-01"}
            }).json()
            self.assertTrue(created["ok"])
            entry_id = created["entry"]["id"]
            client.post(f"/api/safetycheck/{entry_id}/actions", json={"values": {"action": "开始巡检"}})
            hazard = client.post(f"/api/safetycheck/{entry_id}/actions", json={
                "values": {"action": "提交隐患", "隐患等级": "minor", "检查要点": ["gate-02"]}
            }).json()
            self.assertTrue(hazard["ok"])
            self.assertEqual(hazard["entry"]["整改期限"], "2026-10-16")

            reload1 = client.post("/api/safetycheck/config/reload").json()
            reload2 = client.post("/api/safetycheck/config/reload").json()
            self.assertFalse(reload1["changed"])  # 同一份配置重复导入
            self.assertFalse(reload2["changed"])
            # 现场记录仍在
            self.assertEqual(client.get(f"/api/safetycheck/{entry_id}").json()["巡检编号"], "SAFE-HTTP")


if __name__ == "__main__":
    unittest.main()

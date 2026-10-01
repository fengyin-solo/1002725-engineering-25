"""测试夹具：每个用例前后重置安全巡检引导状态与内存仓库，保证用例相互隔离。"""
from __future__ import annotations

import sys
from pathlib import Path

# 允许在未安装包的情况下直接 `python -m unittest` 从 backend 目录运行
BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import unittest  # noqa: E402

from app.safetycheck import reset_for_tests  # noqa: E402
from app.store import store  # noqa: E402

MODULE = "safetycheck"


class SafetycheckTestCase(unittest.TestCase):
    def setUp(self) -> None:
        reset_for_tests()
        store.clear(MODULE)

    def tearDown(self) -> None:
        reset_for_tests()
        store.clear(MODULE)

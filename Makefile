.PHONY: install backend frontend check-config test-backend test

install:
	cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
	cd frontend && npm install

backend:
	cd backend && ./run.sh

frontend:
	cd frontend && npm run dev

# 部署前校验安全巡检依赖与配置：缺项会以非零退出码失败并逐项指出缺哪一个
check-config:
	cd backend && .venv/bin/python -m app.safetycheck.cli validate

# 校验并幂等初始化示例数据（重复执行不覆盖已有巡检记录）
import-config:
	cd backend && .venv/bin/python -m app.safetycheck.cli import

test-backend:
	cd backend && PYTHONPATH=. .venv/bin/python -m unittest discover -s tests -v

test: test-backend
	cd frontend && npm run typecheck

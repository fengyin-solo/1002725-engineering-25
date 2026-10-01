# 港口集装箱作业管理平台

面向港口集装箱码头船舶靠离泊、岸桥装卸、堆场翻倒、闸口进出与危险品申报的一体化作业管理后台。

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/            每个业务模块一个页面
│   ├── src/api/              统一请求封装
│   ├── src/stores/           会话与筛选状态
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/          每个业务模块一组接口
│   ├── app/services/         业务规则与状态流转
│   ├── app/inspection.py     安全巡检配置加载、启动校验与幂等导入
│   ├── config/               安全巡检配置与示例数据（随版本库发布）
│   └── app/store.py          内存数据仓库与示例数据
├── docs/
│   └── safetycheck-config.md 安全巡检配置说明（要点分组、整改期限、导入规则）
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8000/api/health`

### 前端

```bash
cd frontend
npm install
npm run dev
```

前端默认监听 `http://127.0.0.1:5173/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8000`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 泊位计划 | `berth` | 泊位 | 泊位编号、泊位长度、水深条件 |
| 船舶作业 | `vessel` | 船舶 | 船舶编号、船名、船公司 |
| 岸桥调度 | `quaycrane` | 岸桥 | 岸桥编号、岸桥型号、额定起重量 |
| 堆场策划 | `yardplan` | 箱位 | 箱位编号、所在箱区、贝位号 |
| 场桥调度 | `rtg` | 场桥 | 场桥编号、场桥型号、作业箱区 |
| 内集卡调度 | `truck` | 内集卡 | 集卡编号、车牌号码、所属车队 |
| 集装箱信息 | `container` | 集装箱 | 箱号、箱型尺寸、箱主代码 |
| 闸口管理 | `gate` | 进出闸 | 闸口编号、闸口类型、车道编号 |
| 危险品申报 | `dangerous` | 危险品 | 申报编号、箱号、危品类别 |
| 冷藏箱监控 | `coldchain` | 冷藏箱 | 冷藏箱号、设定温度、当前温度 |
| 绑扎加固 | `lashing` | 绑扎任务 | 绑扎编号、对应船舶、箱位范围 |
| 工班管理 | `shift` | 工班 | 工班编号、工班名称、当班组长 |
| 箱体修洗 | `repair` | 修洗任务 | 任务编号、箱号、损伤类型 |
| 理货记录 | `tally` | 理货记录 | 理货编号、对应船舶、箱量核对 |
| 海关查验 | `customs` | 查验记录 | 查验编号、箱号、查验类型 |
| 支线驳船 | `feeder` | 驳船 | 驳船编号、驳船名称、运营公司 |
| 超限箱管理 | `oog` | 超限箱 | 超限箱号、箱型尺寸、超限方向 |
| 空箱堆存 | `emptystack` | 空箱 | 空箱编号、箱主代码、箱型尺寸 |
| 能耗监测 | `energy` | 能耗记录 | 记录编号、设备类型、设备编号 |
| 安全巡检 | `safetycheck` | 巡检记录 | 巡检编号、巡检区域、巡检日期 |

## 约定

- 每个模块的前端页面在 `frontend/src/views/<模块>/index.vue`，后端接口在
  `backend/app/routers/<模块>.py`，业务规则在 `backend/app/services/<模块>.py`。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 安全巡检配置

安全巡检的巡检要点（按巡检区域分组）、隐患等级的整改期限默认天数与示例数据，
全部维护在 `backend/config/` 下并纳入版本管理：

- 换现场、改要点、调期限只改配置，不用动业务代码；
- 启动时校验配置依赖是否齐全，缺项直接报错并指出缺哪一个；
- 整改期限按「发现日期 + 等级天数」确定性计算，不读系统时钟，
  同一份配置在两个环境的结论一致；
- 示例数据按巡检编号幂等导入，重复导入只生效一次，不覆盖已有巡检记录。

详细字段、校验口径与换现场步骤见 [docs/safetycheck-config.md](docs/safetycheck-config.md)。

后端测试：

```bash
cd backend
.venv/bin/python -m unittest discover -s tests
```

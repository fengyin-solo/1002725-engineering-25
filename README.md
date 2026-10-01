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
│   ├── app/safetycheck/      安全巡检配置的加载、启动校验与幂等导入
│   ├── app/config_data/      安全巡检配置与示例数据（进版本管理）
│   └── app/store.py          内存数据仓库与示例数据
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

## 安全巡检配置（巡检要点 / 整改期限 / 示例数据）

安全巡检模块的检查要点、巡检区域、隐患等级与整改期限默认天数不再硬编码在代码里，
而是做成可维护的配置，随版本管理一起发布。**换现场只改配置，不改业务代码。**

### 配置文件

| 文件 | 内容 |
| --- | --- |
| `backend/app/config_data/safetycheck.yaml` | 依赖声明 `requires`、隐患等级与默认整改天数 `hazard_levels`、巡检区域 `areas`、按区域分组的检查要点 `checkpoint_groups` |
| `backend/app/config_data/safetycheck.seed.yaml` | 部署时初始化用的示例巡检记录，用编码引用上面的区域与检查要点 |

- 检查要点按巡检区域分组（`checkpoint_groups[].area` 指向 `areas[].code`）。
- 整改期限默认天数按隐患等级配置（`hazard_levels[].default_deadline_days`）；
  提交隐患时若未手填期限，系统按「巡检日期 + 默认天数」确定性计算到期日。
- 配置目录可用环境变量 `SAFETY_CONFIG_DIR` 覆盖（默认就是 `app/config_data`）。

### 启动校验：缺项直接报错

服务启动（FastAPI lifespan）时会先执行校验，任一缺项都**拒绝启动**并逐项指出缺哪一个：

- 第三方依赖（`requires`）能否导入，缺了给出安装命令；
- 配置文件是否存在、是否合法 YAML、是否有版本号；
- `hazard_levels` / `areas` / `checkpoint_groups` 是否齐全、编码是否重复；
- 每个区域是否都配了检查要点，要点引用的等级、区域是否存在；
- 示例数据引用的区域 / 要点 / 等级是否存在、要点是否属于该记录区域；
- 示例数据的整改期限是否与「巡检日期 + 等级默认天数」一致。

部署前也可以单独校验或幂等初始化（非零退出码可直接接进流水线）：

```bash
make check-config     # 仅校验配置，缺项报错并指出缺哪一个
make import-config    # 校验并幂等初始化示例数据
```

### 幂等导入：重复导入只生效一次，且不覆盖已有记录

- 以配置文件内容的 **SHA-256 指纹**判重：同一份配置重复导入（重启或调用
  `POST /api/safetycheck/config/reload`）直接跳过，返回 `changed=false`，只生效一次。
- 导入只刷新区域 / 等级 / 检查要点等**主数据**；示例数据按「巡检编号」判重，
  已存在的巡检记录（含运行期新建、被状态流转改过的）**一律跳过、绝不覆盖**。

### 跨环境结论一致

- 区域 / 等级 / 要点都用稳定编码（`code`）标识，不随环境变化；
- 整改期限是「巡检日期 + 配置天数」的纯计算结果，不含随机数或当前时间；
- 因此同一份配置在两个环境初始化出的记录、ID、到期日完全一致。
  测试见 `backend/tests/test_safetycheck_config.py`（`make test-backend`）。

### 运行时接口

- `GET /api/safetycheck/config`：返回当前生效的区域、分组要点、等级与默认天数，前端据此渲染；
- `POST /api/safetycheck/config/reload`：换现场改完配置后热加载，重新校验并幂等生效，不影响已有巡检记录；
- 列表支持按区域编码过滤：`GET /api/safetycheck?area=yard`。

前端「安全巡检」页面的区域下拉、要点勾选、等级与默认期限均来自 `/config`，页面内不再硬编码。

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
- 安全巡检的区域 / 检查要点 / 隐患等级 / 整改期限默认天数只在
  `app/config_data/*.yaml` 维护；新增、修改现场配置后跑 `make check-config` 自检，
  不要把具体区域或天数字面量写回业务代码。
- 运行测试：`make test`（后端用标准库 `unittest`，HTTP 用例需安装 `httpx`）。


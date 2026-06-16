# NineHub — Agent 指南

NineHub = **Catalog-driven 数据平台**：TIA 治理规格，Task/Workflow 编排采集，Query Engine 统一消费，`platform_jobs` 承载长任务可观测性。

## 必读文档

| 文档 | 用途 |
|------|------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 终稿架构、C4、数据流 |
| [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) | 需求 vs 实现对照（路线图对齐） |
| [docs/UI_DESIGN.md](docs/UI_DESIGN.md) | 前端壳层与页面 |
| [docs/DATA_NAMING_STANDARD.md](docs/DATA_NAMING_STANDARD.md) | 接口/表名/字段名命名规范（多数据源） |
| [docs/ARCHITECTURE.md#11-cursor-规则注册表终稿](docs/ARCHITECTURE.md#11-cursor-规则注册表终稿) | 16 条 `.cursor/rules/` |

## 仓库结构

```
ninehub/
├── backend/app/          # FastAPI、Celery、catalog、sync
├── backend/static/       # Vue SPA 构建产物（生产托管）
├── frontend/src/         # Vue 3 源码
├── docs/                 # 架构与实施文档
└── .cursor/rules/        # Cursor 规则（按域分包）
```

## 常用命令

```bash
# 后端
cd backend && pip install -e ".[dev]"
python scripts/init_db.py          # PG 用户/库/迁移/seed admin
uvicorn app.main:app --host 127.0.0.1 --port 8888 --reload
pytest tests -v -p no:pytest_postgresql

# 前端
cd frontend && npm install
npm run dev                        # :5173 → proxy :8888
npm run build                      # → backend/static/
```

默认登录：`admin` / `admin123456`（init_db 创建）。

## 按任务选规则

| 工作内容 | 优先阅读规则 |
|----------|----------------|
| API / 分页 / 路由 | `api.mdc`, `rbac.mdc` |
| 采集任务 / Handler | `sync-config.mdc`, `collector.mdc`, `tushare-quota.mdc`, `data-naming.mdc` |
| 工作流 DAG | `workflow.mdc` |
| TIA 扫描 / L3 | `tia.mdc`, `platform-jobs.mdc`, `data-naming.mdc` |
| 质检 | `quality.mdc` |
| 模型 / 迁移 | `database.mdc`, `alembic.mdc` |
| 前端 Vue/CSS | `frontend-lint.mdc` |
| 测试 | `testing.mdc` |

## 架构约束（摘要）

1. **平台能力 ≠ catalog 内容**：新 `data_type` 优先 TIA L3，禁止在 `SyncExecutor` 写 `if data_type == "xxx"`。
2. **长任务**必须写 `platform_jobs`，禁止仅内存进度。
3. **RBAC**：写运维/TIA/任务/数据源 = `admin`；报告与历史读 = 已认证用户。
4. **前端**：列/类型来自 catalog API，禁止硬编码业务列。

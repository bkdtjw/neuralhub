# NeuralHub - 项目约束

## 代码规范
- Python 3.12+，全面使用 type hints
- 类型定义统一用 Pydantic v2 BaseModel
- 单文件不超过 200 行，超过必须拆分
- 模块间只通过 __init__.py 暴露的接口通信
- 所有异步函数必须 try-except，错误用自定义 Exception 类
- 函数参数超过 3 个时用 dataclass 或 Pydantic model 封装

## 架构规则
- backend/core/ 不依赖 FastAPI，纯 Python + asyncio
- backend/core/ 不直接调用 LLM API，通过注入的 adapter 调用
- 工具通过 ToolRegistry 注册，禁止硬编码
- 每个 s01-s12 模块的 __init__.py 是唯一公开入口
- backend/api/ 是唯一的 HTTP 入口层，负责请求验证和响应格式化

## 依赖约束
- 能用标准库解决的不引入第三方包
- 新增 pip 依赖前必须说明理由
- 核心依赖: pydantic, fastapi, uvicorn, httpx

## 测试
- 每个公开接口至少一个测试用例
- 用 pytest + pytest-asyncio
- mock 外部 API 调用，不在测试中发真实请求

## 命名约定
- 文件名: snake_case
- 类名: PascalCase
- 函数/变量: snake_case
- 常量: UPPER_SNAKE_CASE

## Event Hooks 协作（Codex 读这里）
- 总计划: `docs/event-hooks-plan.md`；任务规格: `docs/event-hooks-p{N}-spec.md`（每个 task 一张，本次 prompt 会指明哪张）。
- 你的地盘: 默认只在 `backend/core/s07_task_system/event_hooks/` 内写引擎；接线阶段由规格卡显式授权额外文件（如 P3 的 `backend/api/routes/hooks*.py` + `app.py` 三行接线）。**任何时候都不要碰 `frontend/`**（前端由 Claude 写）。
- wire 契约是唯一真相源: 后端 JSON 字段必须与 `frontend/src/types/hooks.ts` 的 snake_case 对应版**逐字一致**（camelCase↔snake_case 仅大小写差异）。
- 纯/接线分层: 纯包 `event_hooks/`（models/store/retrieval/scoring/assess/runner）**永不** import s02/adapters/fastapi，全靠注入端口；真实接线放 sibling 包 `event_hooks_runtime/`，那里**才**允许 import s02_tools/backend.adapters/backend.config（它是指定的 impure 接缝）。
- 复用不重写: 存储照 `s07_task_system/store.py` + `storage/task_config_store.py` 两层模式；调度复用 `cron_scheduler.py`；源健康复用 `s02_tools/builtin/product_source_health.py`；推特检索复用 `collect_pipeline` / x_client。
- 审核红线（Claude 按这些审你的 diff）: ① 契约字段逐字对齐 ② 推特 `from:` 语法 + 账号/话题分源打标 ③ 推送前跨源去重(一事一推) ④ 盯号也要过 materiality 闸(防狼来了) ⑤ 置信分级(未证实软提示/确认才推) ⑥ 源静默死亡大声告警 ⑦ Pydantic v2 / 单文件<200行 / `__init__` 唯一入口 / 每公开接口配测试 / mock 外部 API。
- 完工后只报告: 改了哪些文件、公开接口签名、测试结果；不要自行改 `frontend/`、`config/`、`docs/` 以外的既有文件。

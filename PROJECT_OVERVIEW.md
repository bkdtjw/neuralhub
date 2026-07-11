# NeuralHub 项目全面梳理

> 最后更新：2026-04-18

## 项目概述

NeuralHub 是一个自建的 AI Coding Agent 平台，提供 Web 界面、OpenAI 兼容 API 以及完整的 Agent 引擎。它是一个全栈应用，支持多 LLM Provider、MCP 协议、子 Agent 协作、定时任务和飞书集成。

### 技术栈

| 层级 | 技术选型 |
|------|----------|
| 后端 | Python 3.12+ / FastAPI / Pydantic v2 / httpx / SQLAlchemy |
| 前端 | React 19 / Vite / Tailwind / Zustand / Monaco Editor |
| 通信 | WebSocket (实时流) + SSE (OpenAI streaming 兼容) |
| 存储 | SQLite (开发) / PostgreSQL (生产) + Redis (可选) |
| LLM | Anthropic Claude / OpenAI / Ollama / OpenAI 兼容接口 |

---

## 目录结构

```
agent-studio/
├── backend/                    # Python 后端
│   ├── main.py                 # uvicorn 入口
│   ├── cli.py                  # CLI 命令行入口 (miniclaude)
│   ├── build_backend.py        # 后端构建脚本
│   ├── config/
│   │   └── settings.py         # Pydantic Settings 配置
│   ├── api/                    # FastAPI 路由层 (唯一 HTTP 入口)
│   │   ├── app.py              # 应用工厂，lifespan 管理
│   │   ├── router.py           # 路由注册
│   │   ├── deps.py             # 依赖注入
│   │   ├── routes/             # 路由实现
│   │   │   ├── chat_completions.py  # OpenAI 兼容 /v1/chat/completions
│   │   │   ├── websocket.py        # WebSocket 实时通信
│   │   │   ├── sessions.py         # 会话管理
│   │   │   ├── providers.py        # LLM Provider 管理
│   │   │   ├── mcp.py              # MCP 服务器管理
│   │   │   ├── reports.py          # 报告生成
│   │   │   ├── feishu.py           # 飞书事件接收
│   │   │   ├── feishu_handler.py   # 飞书消息处理
│   │   │   └── feishu_card_action.py  # 飞书卡片交互
│   │   └── middleware/
│   │       ├── auth.py            # 认证中间件
│   │       ├── rate_limit.py      # 限流
│   │       ├── error_handler.py   # 错误处理
│   │       └── openai_compat.py   # OpenAI 格式转换
│   ├── adapters/               # LLM 适配器
│   │   ├── base.py             # LLMAdapter 抽象基类
│   │   ├── factory.py          # 适配器工厂
│   │   ├── anthropic_adapter.py # Anthropic Claude
│   │   ├── openai_adapter.py   # OpenAI / 兼容接口
│   │   ├── ollama_adapter.py   # Ollama 本地模型
│   │   ├── provider_manager.py # Provider 管理器
│   │   └── provider_seed_loader.py  # 种子配置加载
│   ├── common/                 # 公共模块
│   │   ├── errors.py           # AgentError, ToolError, LLMError
│   │   ├── logger.py           # 日志配置
│   │   ├── utils.py            # 工具函数
│   │   └── types/              # Pydantic 类型定义
│   │       ├── message.py      # Message, ToolCall, ToolResult
│   │       ├── tool.py         # ToolDefinition, ToolParameterSchema
│   │       ├── agent.py        # AgentConfig, AgentEvent, AgentStatus
│   │       ├── llm.py          # LLMRequest, LLMResponse
│   │       ├── session.py      # Session 配置
│   │       ├── mcp.py          # MCP 相关类型
│   │       ├── sub_agent.py    # 子 Agent 相关类型
│   │       └── security.py     # 安全策略类型
│   ├── core/                   # Agent 引擎 (纯 Python，不依赖 FastAPI)
│   │   ├── system_prompt.py    # 系统提示词生成
│   │   ├── s01_agent_loop/     # 主循环 + 状态机
│   │   │   └── agent_loop.py   # AgentLoop 核心类
│   │   ├── s02_tools/          # 工具系统
│   │   │   ├── registry.py     # ToolRegistry 工具注册表
│   │   │   ├── executor.py     # ToolExecutor 工具执行器
│   │   │   ├── security_gate.py # SecurityGate 安全关卡
│   │   │   ├── builtin/        # 内置工具
│   │   │   │   ├── file_read.py    # Read 工具
│   │   │   │   ├── file_write.py   # Write 工具
│   │   │   │   ├── bash.py         # Bash 工具
│   │   │   │   ├── dispatch_agent.py  # dispatch_agent 工具
│   │   │   │   ├── orchestrate_agents.py # orchestrate_agents 工具
│   │   │   │   ├── feishu_notify.py  # 飞书通知
│   │   │   │   ├── youtube_search.py # YouTube 搜索
│   │   │   │   ├── x_search.py       # X/Twitter 搜索
│   │   │   │   ├── proxy_*.py        # 代理管理工具
│   │   │   │   └── task_scheduler.py # 定时任务工具
│   │   │   └── mcp/            # MCP 协议支持
│   │   │       ├── client.py        # MCPClient
│   │   │       ├── server_manager.py # MCPServerManager
│   │   │       └── tool_bridge.py   # MCPToolBridge
│   │   ├── s03_todo_write/     # 任务规划 (预留)
│   │   ├── s04_sub_agents/     # 子 Agent 系统
│   │   │   ├── spawner.py          # SubAgentSpawner
│   │   │   ├── lifecycle.py        # SubAgentLifecycle
│   │   │   ├── orchestrator.py     # Orchestrator 多 Agent 编排
│   │   │   ├── agent_definition.py # AgentDefinitionLoader
│   │   │   ├── permission_policy.py # 权限策略
│   │   │   └── isolated_runner.py  # 隔离运行
│   │   ├── s05_skills/         # 技能系统 (预留)
│   │   ├── s06_context_compression/  # 上下文压缩
│   │   │   ├── compressor.py       # ContextCompressor
│   │   │   ├── threshold_policy.py # ThresholdPolicy
│   │   │   └── token_counter.py    # TokenCounter
│   │   ├── s07_task_system/    # 定时任务系统
│   │   │   ├── models.py           # ScheduledTask 模型
│   │   │   ├── store.py            # TaskStore
│   │   │   ├── scheduler.py        # TaskScheduler
│   │   │   └── executor.py         # TaskExecutor
│   │   ├── s08_background_tasks/    # 后台任务 (预留)
│   │   ├── s09_agent_teams/    # Agent 团队 (预留)
│   │   ├── s10_team_protocol/  # 团队协议 (预留)
│   │   ├── s11_autonomous_agent/   # 自主 Agent (预留)
│   │   ├── s12_worktree_isolation/ # Worktree 隔离 (预留)
│   │   └── permissions/        # 权限规则
│   ├── schemas/                # API 请求/响应 Schema
│   │   ├── completion.py       # ChatCompletionRequest/Response
│   │   ├── session.py          # Session Schema
│   │   ├── tool.py             # Tool Schema
│   │   ├── provider.py         # Provider Schema
│   │   ├── task.py             # Task Schema
│   │   ├── team.py             # Team Schema
│   │   ├── agent.py            # Agent Schema
│   │   ├── message.py          # Message Schema
│   │   └── events.py           # Event Schema
│   ├── storage/                # 数据存储
│   │   ├── database.py         # 数据库初始化
│   │   ├── models.py           # SQLAlchemy ORM 模型
│   │   ├── session_store.py    # SessionStore
│   │   ├── provider_store.py   # ProviderStore
│   │   ├── mcp_server_store.py # MCPServerStore
│   │   ├── task_config_store.py # TaskConfigStore
│   │   ├── serializers.py      # 序列化器
│   │   └── file_store.py       # 文件存储 (预留)
│   ├── cli_support/            # CLI 支持
│   └── tests/                  # 后端测试
├── frontend/                   # React 前端
│   ├── src/
│   │   ├── App.tsx             # 主应用
│   │   ├── main.tsx            # 入口
│   │   ├── pages/              # 页面组件
│   │   │   ├── Dashboard.tsx   # 仪表板
│   │   │   ├── Session.tsx     # 会话页
│   │   │   ├── Settings.tsx    # 设置页
│   │   │   └── Teams.tsx       # 团队页
│   │   ├── components/         # UI 组件
│   │   │   ├── chat/           # 聊天组件
│   │   │   ├── editor/         # 编辑器
│   │   │   ├── diff/           # Diff 视图
│   │   │   ├── terminal/       # 终端
│   │   │   ├── task-board/     # 任务板
│   │   │   ├── agent-panel/    # Agent 面板
│   │   │   └── sidebar/        # 侧边栏
│   │   ├── stores/             # Zustand 状态管理
│   │   ├── hooks/              # React Hooks
│   │   ├── lib/                # 工具库
│   │   └── types/              # TypeScript 类型
│   ├── package.json
│   └── vite.config.ts
├── skills/                     # 技能定义
│   ├── builtin/                # 内置技能
│   │   ├── code_review/        # 代码审查
│   │   ├── debug/              # 调试
│   │   ├── deploy/             # 部署
│   │   ├── doc_gen/            # 文档生成
│   │   ├── refactor/           # 重构
│   │   └── test_gen/           # 测试生成
│   ├── community/              # 社区技能
│   └── templates/              # 技能模板
├── agents/                     # Agent 角色定义
│   ├── builtin/                # 内置 Agent
│   │   ├── planner/            # 规划者
│   │   ├── explorer/           # 探索者
│   │   ├── implementer/        # 实现者
│   │   ├── reviewer/           # 审查者
│   │   ├── tester/             # 测试者
│   │   └── verifier/           # 验证者
│   ├── custom/                 # 自定义 Agent
│   └── examples/               # Agent 示例
├── tests/                      # 集成测试
├── config/                     # TOML 配置文件
├── deploy/                     # 部署配置
│   ├── docker/                 # Docker 配置
│   ├── k8s/                    # Kubernetes 配置
│   └── scripts/                # 部署脚本
├── docs/                       # 文档
│   ├── architecture/           # 架构文档
│   │   ├── overview.md         # 架构概述
│   │   ├── tool-system.md      # 工具系统
│   │   ├── agent-loop.md       # Agent 循环
│   │   └── team_protocol.md    # 团队协议
│   ├── api/                    # API 文档
│   │   ├── rest_api.md         # REST API
│   │   ├── websocket.md        # WebSocket
│   │   └── openai-compat.md    # OpenAI 兼容
│   └── guides/                 # 使用指南
├── scripts/                    # 工具脚本
├── CLAUDE.md                   # 项目约束规范
├── AGENTS.md                   # Agent 约束规范
├── README.md                   # 项目说明
├── Makefile                    # 构建命令
├── pyproject.toml              # Python 项目配置
├── docker-compose.yml          # Docker Compose
└── .env.example                # 环境变量示例
```

---

## 核心模块详解

### 1. Agent 循环 (s01_agent_loop)

**文件**: `backend/core/s01_agent_loop/agent_loop.py`

**类**: `AgentLoop`

**职责**:
- 实现 Agent 主循环逻辑
- 管理 Agent 状态 (idle, thinking, compacting, tool_calling, done, error)
- 处理消息序列和工具调用
- 集成上下文压缩和安全检查

**关键方法**:
- `run(user_message: str) -> Message`: 运行 Agent 循环
- `abort()`: 中止执行
- `reset()`: 重置状态
- `on(handler)`: 注册事件处理器

**事件流**:
```
user_input → thinking → compacting (if needed) → LLM request →
message event → tool_call event → tool_result event →
repeat until done or max_iterations
```

---

### 2. 工具系统 (s02_tools)

**核心组件**:

#### 2.1 ToolRegistry (`registry.py`)
- 管理工具注册表
- 提供 `register()`, `get()`, `list_definitions()`, `remove()` 方法

#### 2.2 ToolExecutor (`executor.py`)
- 执行工具调用
- 支持批量执行和签名验证

#### 2.3 SecurityGate (`security_gate.py`)
- 实现工具调用的安全检查
- HMAC 签名验证
- 拒绝非授权工具调用

#### 2.4 内置工具 (`builtin/`)

| 工具名 | 功能 | 权限要求 |
|--------|------|----------|
| Read | 读取文件内容 | readonly |
| Write | 写入文件 | auto/full |
| Bash | 执行 shell 命令 | auto/full |
| dispatch_agent | 派发子 Agent | auto/full |
| orchestrate_agents | 编排多 Agent | auto/full |
| feishu_notify | 飞书通知 | 需 webhook URL |
| youtube_search | YouTube 搜索 | 需 API Key |
| x_search | X/Twitter 搜索 | 需账号凭证 |
| proxy_* | 代理管理工具 | 需 mihomo 配置 |
| task_scheduler | 定时任务管理 | - |

#### 2.5 MCP 支持 (`mcp/`)
- **MCPClient**: 连接 MCP 服务器
- **MCPServerManager**: 管理多个 MCP 服务器
- **MCPToolBridge**: 将 MCP 工具桥接到工具注册表

---

### 3. 子 Agent 系统 (s04_sub_agents)

**核心组件**:

#### 3.1 SubAgentSpawner (`spawner.py`)
- 创建并运行子 Agent
- 继承父 Agent 的工具注册表
- 支持自定义系统提示词

#### 3.2 Orchestrator (`orchestrator.py`)
- 执行多 Agent 协作计划
- 支持阶段依赖解析
- 并行执行同阶段任务

#### 3.3 内置 Agent 角色

| 角色 | 描述 | 允许工具 | 最大迭代 |
|------|------|----------|----------|
| planner | 任务拆解、计划设计 | Read, Bash | 6 |
| explorer | 代码探索、信息提炼 | Read, Bash | 8 |
| implementer | 代码实现 | Read, Write, Bash | 8 |
| reviewer | 代码审查 | Read, Bash | 8 |
| tester | 测试设计 | Read, Bash | 8 |
| verifier | 修复验证 | Read, Bash | 8 |

---

### 4. 上下文压缩 (s06_context_compression)

**核心组件**:

#### 4.1 ContextCompressor (`compressor.py`)
- 当 Token 数量超过阈值时触发压缩
- 使用 LLM 生成对话历史摘要
- 保留最近 N 条消息不被压缩

#### 4.2 ThresholdPolicy (`threshold_policy.py`)
- 定义压缩阈值 (默认 100000 tokens)
- 定义保留消息数量 (默认 8 条)

#### 4.3 TokenCounter (`token_counter.py`)
- 估算消息和工具定义的 Token 数量

---

### 5. 定时任务系统 (s07_task_system)

**核心组件**:

#### 5.1 TaskScheduler (`scheduler.py`)
- 基于 cron 表达式的任务调度
- 支持时区配置
- 错过任务恢复机制

#### 5.2 TaskExecutor (`executor.py`)
- 执行定时任务
- 支持 LLM 调用和 MCP 工具
- 飞书卡片发送

#### 5.3 TaskStore (`store.py`)
- 任务配置的持久化存储
- 支持数据库和 JSON 文件

**任务模型**:
```python
class ScheduledTask:
    id: str
    name: str
    cron: str              # cron 表达式
    timezone: str          # 时区
    prompt: str            # 执行提示词
    notify: NotifyConfig   # 通知配置
    output: OutputConfig   # 输出配置
    enabled: bool
```

---

### 6. LLM 适配器 (adapters)

**基类**: `LLMAdapter` (`adapters/base.py`)

**实现**:
- `AnthropicAdapter`: Anthropic Claude API
- `OpenAIAdapter`: OpenAI / 兼容接口
- `OllamaAdapter`: Ollama 本地模型

**ProviderManager**:
- 管理多个 LLM Provider
- 支持动态添加、更新、删除
- 自动设置默认 Provider
- 连接测试

---

### 7. API 路由 (api/routes)

| 路由 | 功能 | 方法 |
|------|------|------|
| `/v1/chat/completions` | OpenAI 兼容聊天接口 | POST |
| `/ws` | WebSocket 实时通信 | WebSocket |
| `/sessions` | 会话管理 | GET/POST/DELETE |
| `/providers` | Provider 管理 | CRUD |
| `/mcp` | MCP 服务器管理 | CRUD |
| `/reports` | 报告生成 | POST |
| `/api/feishu/event` | 飞书事件接收 | POST |
| `/health` | 健康检查 | GET |

---

### 8. 存储层 (storage)

**ORM 模型** (`models.py`):
- `SessionRecord`: 会话记录
- `MessageRecord`: 消息记录
- `ProviderRecord`: Provider 配置
- `MCPServerRecord`: MCP 服务器配置
- `ScheduledTaskRecord`: 定时任务配置

**存储类**:
- `SessionStore`: 会话 CRUD
- `ProviderStore`: Provider CRUD
- `MCPServerStore`: MCP 服务器 CRUD
- `TaskConfigStore`: 任务配置 CRUD

---

### 9. 飞书集成

**功能**:
1. **单向通知**: 通过 Webhook 发送消息
2. **双向通信**: 企业自建应用，接收和处理消息
3. **卡片交互**: 支持按钮回调，如重新运行任务

**相关文件**:
- `api/routes/feishu.py`: 事件接收
- `api/routes/feishu_handler.py`: 消息处理
- `api/routes/feishu_card_action.py`: 卡片交互
- `core/s02_tools/builtin/feishu_client.py`: 飞书客户端

---

## 配置说明

### 环境变量 (.env)

```bash
# === Provider API Keys ===
ANTHROPIC_API_KEY=sk-ant-xxx
OPENAI_API_KEY=sk-xxx
OLLAMA_BASE_URL=http://localhost:11434
DEFAULT_PROVIDER=anthropic
DEFAULT_MODEL=claude-sonnet-4-20250514

# === Server ===
API_HOST=127.0.0.1
API_PORT=8000

# === Database ===
DATABASE_URL=sqlite+aiosqlite:///./data/agent_studio.db
REDIS_URL=redis://localhost:6379/0

# === Feishu ===
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
FEISHU_WEBHOOK_SECRET=
FEISHU_APP_ID=
FEISHU_APP_SECRET=

# === YouTube ===
YOUTUBE_API_KEY=
YOUTUBE_PROXY_URL=http://127.0.0.1:7890

# === X/Twitter ===
TWITTER_USERNAME=
TWITTER_EMAIL=
TWITTER_PASSWORD=
TWITTER_PROXY_URL=http://127.0.0.1:7890

# === Proxy (mihomo) ===
MIHOMO_API_URL=http://127.0.0.1:9090
MIHOMO_SECRET=
MIHOMO_PATH=/path/to/mihomo
MIHOMO_CONFIG_PATH=/path/to/config.yaml
```

---

## 快速开始

### 安装
```bash
make install
```

### 开发
```bash
# 启动后端
make dev-api

# 启动前端
make dev-frontend
```

### 测试
```bash
make test
```

### 构建
```bash
make build-all
```

---

## 关键设计原则

1. **core/ 与 api/ 完全解耦**: core 是纯 asyncio 代码，可以脱离 FastAPI 单独使用
2. **适配器模式**: LLM 调用通过抽象基类 LLMAdapter 注入
3. **Pydantic 贯穿全栈**: 类型定义、请求验证、序列化全用 Pydantic v2
4. **模块间通信**: 只通过 `__init__.py` 暴露的接口通信
5. **工具注册**: 通过 ToolRegistry 注册，禁止硬编码
6. **权限模式**: readonly / auto / full 三种权限模式
7. **单一入口**: backend/api/ 是唯一的 HTTP 入口层

---

## 扩展指南

### 添加新工具
1. 在 `backend/core/s02_tools/builtin/` 创建工具文件
2. 实现工具函数，返回 `ToolDefinition` 和执行函数
3. 在 `builtin/__init__.py` 中注册

### 添加新 Agent 角色
1. 在 `agents/builtin/` 创建角色目录
2. 创建 `agent.md` 文件，定义角色配置
3. 使用 `dispatch_agent` 或 `orchestrate_agents` 调用

### 添加新 LLM Provider
1. 在 `backend/adapters/` 创建适配器
2. 继承 `LLMAdapter` 基类
3. 在 `AdapterFactory` 中注册

### 添加新技能
1. 在 `skills/builtin/` 创建技能目录
2. 创建 `SKILL.md` 文件
3. 通过技能系统加载

---

## 项目规范

### 代码规范 (CLAUDE.md)
- Python 3.12+，全面使用 type hints
- 类型定义统一用 Pydantic v2 BaseModel
- 单文件不超过 200 行
- 模块间只通过 `__init__.py` 暴露接口
- 所有异步函数必须 try-except
- 函数参数超过 3 个用 dataclass 封装

### 命名约定
- 文件名: `snake_case`
- 类名: `PascalCase`
- 函数/变量: `snake_case`
- 常量: `UPPER_SNAKE_CASE`

---

## 已知功能特性

### 核心功能
- [x] OpenAI 兼容 API (/v1/chat/completions)
- [x] WebSocket 实时流
- [x] 多 LLM Provider 支持
- [x] MCP 协议支持
- [x] 子 Agent 派发
- [x] 多 Agent 编排
- [x] 上下文压缩
- [x] 定时任务 (cron)
- [x] 飞书集成 (通知 + 双向)
- [x] 工具权限控制
- [x] 会话管理
- [x] Provider 管理
- [x] CLI 命令行工具 (miniclaude)

### 工具集成
- [x] 文件读写
- [x] Bash 命令执行
- [x] YouTube 搜索 (API Key + yt-dlp)
- [x] X/Twitter 搜索
- [x] 飞书通知
- [x] Mihomo 代理管理

### 前端功能
- [x] 仪表板
- [x] 会话管理
- [x] 设置页面
- [x] 聊天界面
- [x] Diff 视图
- [x] 终端
- [x] 任务板
- [x] Agent 面板

---

## 依赖项

### Python 核心依赖
```
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
pydantic>=2.9.0
pydantic-settings>=2.5.0
httpx>=0.27.0
redis>=5.0.0
hiredis>=3.0.0
websockets>=13.0
aiosqlite>=0.20.0
asyncpg>=0.29.0
sqlalchemy[asyncio]>=2.0.0
python-dotenv>=1.0.0
croniter>=2.0.0
markdown>=3.5.0
```

### 前端依赖
```
react@^19.0.0
react-dom@^19.0.0
react-router-dom@^7.0.0
zustand@^5.0.0
diff2html@^3.4.48
vite@^6.0.0
tailwindcss@^3.4.0
typescript@^5.5.0
```

---

## 常见问题

### Q: 如何切换 LLM Provider？
A: 通过 `/providers` API 或在设置页面添加新的 Provider，然后设置为默认。

### Q: 如何添加 MCP 服务器？
A: 通过 `/mcp` API 或在设置页面添加 MCP 服务器配置。

### Q: 如何创建定时任务？
A: 通过 `task_scheduler` 工具或直接调用 `/tasks` API。

### Q: 子 Agent 和主 Agent 的区别？
A: 子 Agent 继承父 Agent 的工具注册表，有独立的系统提示词和执行上下文，适合处理特定子任务。

---

## 项目状态

当前版本: `0.1.0`

项目处于活跃开发状态，核心功能已实现，正在完善周边功能和用户体验。

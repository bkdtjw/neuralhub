# NeuralHub

> 曾用名 Agent Studio（2026-07 更名）。历史审计/功能报告类文档中的旧称保留原样。
自建 AI Coding Agent 平台，包含 Web UI、OpenAI 兼容 API、CLI、飞书入口、定时任务，以及基于 Redis 的跨 Worker 子 agent 并行执行。

## 做什么
- 多模型接入：Anthropic、OpenAI、Ollama、OpenAI 兼容接口
- 完整 agent runtime：消息循环、工具调用、安全关卡、上下文压缩
- Skills / AgentSpec：从 `skills/` 目录加载不同场景
- 多入口统一运行时：WebSocket、飞书、CLI、定时任务都走 `AgentRuntime`
- 多 agent 并行：`spawn_agent` 把任务分发到不同 Worker 执行
- 可观测性：结构化日志、指标、前端 `Logs` / `Metrics` 页面
- 生产部署：Docker Compose、Gunicorn、PostgreSQL、Redis

## 入口
| 入口 | 说明 |
| --- | --- |
| Web UI | 会话、设置、日志、指标页面 |
| `POST /v1/chat/completions` | OpenAI 兼容接口，支持流式返回 |
| WebSocket | 实时消息、tool call、sub-agent 进度事件 |
| CLI `miniclaude` | REPL 和 `miniclaude run <spec_id>` |
| 飞书 | 普通消息走主 agent，`/spec_id` 直达 skill |
| 定时任务 | 任务可绑定 `spec_id`，按 AgentSpec 执行 |

## 架构
```text
frontend/ (React + Vite)
  └─ Dashboard / Session / Settings / Logs / Metrics

backend/api/ (FastAPI)
  ├─ /v1/chat/completions
  ├─ /ws
  ├─ /api/feishu/*
  ├─ /logs /metrics /health/*
  └─ lifespan 中初始化 DB / Redis / Skills / Task Queue

backend/core/ (纯 Python)
  ├─ s01_agent_loop
  ├─ s02_tools
  ├─ s05_skills
  ├─ s07_task_system
  ├─ task_queue*
  └─ sub_agent_queue
```

## 关键场景
### Skills / AgentSpec
`skills/` 下的每个 skill 可包含 `SKILL.md`、`prompt.md`、`tools.yaml`、`sub_agents.yaml`。

当前示例：
- `daily-ai-news`
- `code-reviewer`
- `tech-research`

### 跨 Worker `spawn_agent`
主 agent 调用 `spawn_agent` 后，会把子任务写入 Redis，由其他 Worker 领取执行，再把结果写回给主 agent 汇总。当前链路已支持：
- 并行子任务
- 失败回传
- 全局等待超时
- stale task 回收
- WebSocket `sub_agent_spawned` / `sub_agent_completed` / `sub_agent_failed`

### 飞书斜杠命令
```text
/daily-ai-news
/code-reviewer 审查 backend/core/task_queue.py
```

### CLI 一次性执行
```bash
miniclaude run daily-ai-news
miniclaude run code-reviewer -i "审查 backend/core/task_queue.py"
miniclaude -w /path/to/workspace
```

## 快速开始
### 本地开发
1. 安装依赖
```bash
python -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
pip install -r backend/requirements-dev.txt
cd frontend && npm install && cd ..
```

2. 配置环境变量
```bash
cp .env.example .env
```

至少需要配置：
- `DATABASE_URL`
- `REDIS_URL`
- `AUTH_SECRET`
- 一个 provider key，例如 `ANTHROPIC_API_KEY` 或 `OPENAI_API_KEY`

3. 启动后端
```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

或：
```bash
make dev
```

4. 启动前端
```bash
cd frontend && npm run dev
```

或：
```bash
make dev-frontend
```

### Docker Compose
```bash
docker compose up -d --build
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
docker compose ps
```

完整部署说明见 [DEPLOY.md](DEPLOY.md)。

## OpenAI 兼容 API 示例
```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer change-me-in-production" \
  -d '{
    "model": "claude-sonnet-4-20250514",
    "provider_id": "anthropic",
    "messages": [{"role": "user", "content": "读一下 backend/core/task_queue.py"}],
    "stream": true
  }'
```

## Web UI 页面
- `/` 仪表板
- `/session/:id` 会话页
- `/settings` 设置
- `/logs` 日志搜索
- `/metrics` 指标概览

## 运维与排障
- 查看日志：`docker compose logs -f app`
- 健康检查：`/health/live`、`/health/ready`
- Redis 子任务 key：`task:sub_agent:{task_id}`
- 结构化日志字段：`trace_id`、`session_id`、`worker_id`

排查 `spawn_agent` 时重点看：
- `sub_agent_task_submitted`
- `sub_agent_task_claimed`
- `sub_agent_task_completed`
- `sub_agent_task_failed`
- `sub_agent_wait_start`
- `sub_agent_wait_end`
- `stale_task_scan`

## 目录
```text
backend/   FastAPI、agent engine、存储、测试
frontend/  React 前端
skills/    AgentSpec / skill 定义
agents/    agent 角色和插件市场元数据
scripts/   部署和运维脚本
```

## 相关文档
- [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md)：模块梳理
- [DEPLOY.md](DEPLOY.md)：部署和运维说明
- `AGENTS.md`：仓库内 agent 协作约束

## 当前状态
仓库已经覆盖：
- Skills 基础设施
- 多入口 AgentRuntime 接入
- `spawn_agent` 跨 Worker 执行
- 定时任务 `spec_id`
- 飞书斜杠命令
- Logs / Metrics 可观测性页面

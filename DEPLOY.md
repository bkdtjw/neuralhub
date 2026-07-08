# 部署指南

## 前置条件
- Docker
- Docker Compose v2
- PostgreSQL（宿主机或远程）
- Redis（宿主机或远程）

## 环境配置
- 复制 `.env.example` 为 `.env`
- 必填项：`DATABASE_URL`、`REDIS_URL`、`AUTH_SECRET`
- 可选项：`GUNICORN_WORKERS`、`LOG_LEVEL`、`LOG_FORMAT`、`LOG_STDOUT`、`LOG_FILE_ENABLED`、`LOG_FILE_SCOPE`、`LOG_SEARCH_BACKEND`、`LOKI_BASE_URL`、`API_PORT`、`AUTO_CREATE_TABLES`

> **Schema 管理（`AUTO_CREATE_TABLES`）**：默认 `true`，应用启动时由 `init_db` 执行 `create_all` 自动建表（与 entrypoint 的 `alembic upgrade head` 双轨）。生产环境的目标是设为 `false`，让 alembic 迁移成为 schema 的唯一权威，避免"新列只在 model、alembic 漏迁移"的双轨风险。**注意**：当前迁移链尚无覆盖全部核心表的 baseline（链头仅 alter 既有表，`providers.roles` 也只由 `init_db` 补列），因此在补齐 alembic baseline 之前，请勿在全新数据库上直接设 `false`——否则核心表不会被创建。设为 `false` 时 `init_db` 仅做数据库连通性检查。

## Volume 映射
docker-compose.yml 配置了以下 volume 映射：

| 宿主机路径 | 容器内路径 | 说明 |
|-----------|-----------|------|
| `./data/logs` | `/app/data/logs` | 应用日志文件 |
| `./reports` | `/app/reports` | 定时任务执行报告（持久化） |
| `./twitter_cookies.json` | `/app/twitter_cookies.json` | X/Twitter 认证 cookies（可选） |

启动前确保宿主机目录存在：
```bash
mkdir -p data/logs reports
```

> **注意**：entrypoint 脚本会在容器启动时自动修复 volume 挂载目录的权限，无需手动 chown。

### Twitter/X 搜索配置（可选）
如需使用 X 搜索功能，需要：
1. 在 `.env` 中配置 `TWITTER_USERNAME`/`TWITTER_EMAIL`/`TWITTER_PASSWORD`
2. 在项目根目录放置 `twitter_cookies.json` 文件
3. 配置 `TWITTER_PROXY_URL`（国内必需）

注意：如果未配置 Twitter 搜索，可以将 `docker-compose.yml` 中的 cookies 挂载注释掉。

## 启动
```bash
docker compose up -d --build
```

### 启动 Loki 日志检索（推荐生产链路）
```bash
docker compose -f docker-compose.yml -f docker-compose.observability.yml up -d --build
```

该模式会启动：

| 服务 | 端口 | 说明 |
|------|------|------|
| `loki` | `3100` | 日志存储与查询后端 |
| `alloy` | `12345` | 从 Docker stdout 采集应用日志并写入 Loki |
| `grafana` | `3000` | 已预置 Loki 数据源，默认账号 `admin/admin` |

推荐生产环境使用 stdout 作为主采集链路：

```env
LOG_FORMAT=json
LOG_STDOUT=1
LOG_FILE_ENABLED=0
LOG_SEARCH_BACKEND=loki
LOG_SEARCH_FALLBACK=file
LOKI_BASE_URL=http://127.0.0.1:3100
```

`docker-compose.observability.yml` 会默认应用以上关键项。`LOG_SEARCH_FALLBACK=file` 用于 Loki 短暂不可用时回退到本地文件；如果希望 Loki 故障直接暴露为 502，可设置 `LOG_SEARCH_FALLBACK=none`。

镜像默认固定为 `grafana/loki:3.7.1`、`grafana/alloy:v1.15.1`、`grafana/grafana:13.0.1`，可通过 `LOKI_IMAGE`、`ALLOY_IMAGE`、`GRAFANA_IMAGE` 覆盖。

## 验证
```bash
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
docker compose ps
```

### Loki 验证
```bash
curl http://127.0.0.1:3100/ready
curl -G http://127.0.0.1:3100/loki/api/v1/query_range --data-urlencode 'query={app="agent-studio"} | json' --data-urlencode limit=5
```

应用日志 API 会根据 `LOG_SEARCH_BACKEND` 选择后端：

```bash
curl -H "Authorization: Bearer $AUTH_SECRET" \
  "http://127.0.0.1:8000/api/logs/search?event=http_request_end&component=http&minutes=60&limit=20"
```

### 容器内权限验证
```bash
# 验证 appuser 可写目录
docker compose exec app touch /app/reports/test && docker compose exec app rm /app/reports/test
docker compose exec app touch /app/data/logs/test && docker compose exec app rm /app/data/logs/test

# 验证 cookies 文件挂载（如果配置了 Twitter 搜索）
docker compose exec app ls -la /app/twitter_cookies.json
```

## 运维
- 查看日志：`docker compose logs -f app`
- 重启服务：`docker compose restart app`
- 更新代码：`git pull && docker compose up -d --build`
- 回滚到 systemd：`scripts/rollback-to-systemd.sh`

## 架构
- Gunicorn master + N 个 `UvicornWorker`
- WebSocket 通过 Redis pub/sub 跨 Worker 广播，channel 使用 `ws:session:{session_id}`
- 任务队列通过 Redis List 跨 Worker 分发，任务 key 使用 `task:{namespace}:{task_id}`
- 运行时结构化日志统一输出 JSON，包含 `trace_id`、`session_id`、`worker_id`
- `LOG_FILE_SCOPE=worker` 时每个进程写独立日志文件，避免多 Worker 轮转同一个文件
- Loki 链路使用 Docker stdout 采集，不依赖应用进程写共享日志文件
- Loki 索引标签为 `app`、`level`、`component`、`event`；`trace_id`、`session_id`、`worker_id`、`error_code` 保持为 JSON 字段/结构化元数据，避免高基数索引膨胀
- `/api/logs/search` 在 `LOG_SEARCH_BACKEND=file` 时扫描本地文件，在 `LOG_SEARCH_BACKEND=loki` 时查询 Loki

## Skills 目录
- 默认从仓库根目录的 `skills/` 加载所有可用 spec
- 每个 skill 目录至少包含 `SKILL.md`
- 可选文件：`prompt.md`、`tools.yaml`、`sub_agents.yaml`

示例结构：
```text
skills/
  daily-ai-news/
    SKILL.md
    prompt.md
    tools.yaml
  code-reviewer/
    SKILL.md
    prompt.md
```

## 飞书斜杠命令
- 普通消息：走主 agent，对话可持续，并可通过 `query_specs` 发现可用场景
- 斜杠命令：`/spec_id 后续文本`
- 示例：`/daily-ai-news`
- 示例：`/code-reviewer 审查 backend/core/s05_skills/runtime.py`

## CLI Run
- 交互模式保持不变：`miniclaude -w /path/to/workspace`
- 一次性执行 spec：`miniclaude run daily-ai-news`
- 带输入：`miniclaude run code-reviewer -i "审查 backend/core/"`
- 指定工作目录：`miniclaude run tech-research -w /path/to/workspace`

## 定时任务 spec_id
- `scheduled_tasks.spec_id` 为空时，仍按 `prompt` 驱动执行
- `scheduled_tasks.spec_id` 非空时，任务会按对应 spec 的 system prompt、工具白名单和模型/provider 配置执行

# 配置手册

所有配置通过环境变量（`.env` 文件）注入，键名与 `backend/config/settings.py` 一一对应。
复制模板开始：`cp .env.example .env`。

> ⚠️ **部署铁律**：改了 `.env` 必须 `docker compose up -d app`（重建容器）才生效，
> `docker restart` 不会重新读取环境变量；纯代码改动才可以只 restart。

## 一、最小可跑集（4 项必填）

| 键 | 说明 | 示例 |
| --- | --- | --- |
| `DATABASE_URL` | PostgreSQL 连接串（必须 `postgresql` 开头，缺失直接拒绝启动） | `postgresql+asyncpg://agent:密码@postgres:5432/agent_studio` |
| `REDIS_URL` | Redis 连接串（队列/缓存/频控闸门） | `redis://redis:6379/0` |
| `AUTH_SECRET` | 全部受保护 API 的 Bearer token。**生产必改**：`openssl rand -hex 32` | — |
| 任一 Provider Key | 见下节 | — |

`AUTH_SECRET` 同时还是：前端登录 token、浏览器 Cookie 扩展的同步口令（`X-Agent-Studio-Token` 头）。改它要三处一起换。

## 二、LLM Provider

两种配置方式，可混用：

1. **环境变量**（内置三类适配器）：
   - `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL`（走中转就填 base_url）
   - `OPENAI_API_KEY`
   - `OLLAMA_BASE_URL`（默认 `http://localhost:11434`）
   - `DEFAULT_PROVIDER` / `DEFAULT_MODEL`：未在会话里指定时的兜底
2. **Web 设置页**：任意 OpenAI 兼容接口（Kimi、智谱等）在「设置 → Provider」里填 base_url + key，存数据库，运行时热切换，不用重启。

容错链（可选）：`LLM_FALLBACK_PROVIDER_IDS`（逗号分隔的备用 provider，主挂了按序降级）、
`LLM_FALLBACK_CIRCUIT_THRESHOLD`（连败几次熔断，默认 3）、`LLM_FALLBACK_CIRCUIT_SECONDS`（熔断时长，默认 300）。

## 三、X / Twitter（搜索内核 + 舆情雷达）

### 3.1 账号与登录（twikit 内核）

```env
TWITTER_USERNAME=你的X用户名
TWITTER_EMAIL=账号邮箱
TWITTER_PASSWORD=账号密码
TWITTER_PROXY_URL=http://127.0.0.1:7890   # 国内必填，指向你的代理(如 mihomo)
TWITTER_COOKIES_FILE=twitter_cookies.json
```

登录机制：**首次**用账密登录成功后，会话 cookie 持久化到 `TWITTER_COOKIES_FILE`，
之后每次直接用 cookie 免登录（降低风控触发）。Docker 部署把 `twitter_cookies.json`
放在项目根目录（与 docker-compose.yml 同级），容器会挂载到 `/app/twitter_cookies.json`。

> 提醒：twikit 走的是 X 的非官方接口，仅限内部/个人使用；cookie 文件等同账号凭据，
> **绝不能提交进 git**（已在 .gitignore）。

### 3.2 浏览器 Cookie 同步扩展（可选，服务内置浏览器工具）

`extension/` 目录是一个 Chrome 解包扩展：在浏览器登录 x.com 等站点后，
一键把 cookie 同步到后端（`POST /api/cookie/sync`），供内置浏览器自动化工具复用登录态。
安装：`chrome://extensions` → 开发者模式 → 加载已解压 → 选 `extension/`；
在扩展选项页填后端地址和口令（口令 = `AUTH_SECRET`，请求头 `X-Agent-Studio-Token`）。

### 3.3 X 舆情雷达开关与预算（REST API）

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `X_API_ENABLED` | `false` | 总开关；关闭时 `/api/x/*` 路由不注册 |
| `X_MONITOR_ENABLED` | `false` | 监控告警开关；关闭时轮询器不启动 |
| `X_SEARCH_CACHE_TTL_SECONDS` | 300 | 同参数搜索缓存，命中不打 X |
| `X_CALL_MIN_INTERVAL_SECONDS` | 5.0 | 真实调用全局最小间隔 |
| `X_DAILY_CALL_BUDGET` | 200 | 每日调用额度；打满新接口 429，AI 早报不受影响 |
| `X_RANK_WEIGHT_LIKES / _RETWEETS / _VIEWS` | 1 / 2 / 0.01 | 热度加权分权重 |
| `X_MONITOR_MIN_INTERVAL_MINUTES` | 15 | 单条监控最小轮询间隔 |
| `X_MONITOR_MAX_COUNT` | 20 | 监控条数上限 |

API 用法见 [x-api.md](x-api.md)。

## 四、飞书

### 4.1 单向通知（自定义机器人 webhook）——早报/告警推送用

群设置 → 群机器人 → 添加「自定义机器人」，拿到：

```env
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/xxxx
FEISHU_WEBHOOK_SECRET=   # 机器人若勾选"签名校验"则必填，卡片按 HMAC 签名发送
```

### 4.2 双向对话（企业自建应用）——飞书里跟 Agent 聊天用

[open.feishu.cn](https://open.feishu.cn) → 创建企业自建应用：

```env
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
FEISHU_VERIFICATION_TOKEN=   # 事件订阅页的 Verification Token
FEISHU_ENCRYPT_KEY=          # 若开启了事件加密则必填
FEISHU_CHAT_ID=oc_xxx        # 定时任务卡片的目标群（群设置可查）
```

必开权限：`im:message:receive_v1`、`im:message:send_v1`、`im:chat:readonly`；
事件订阅回调地址填：`https://你的域名/api/feishu/event`。

### 4.3 AI 早报接收人

```env
MORNING_REPORT_USER_IDS=default        # 逗号分隔
MORNING_REPORT_CHAT_ID=                # 发到群则填群 chat_id
```

## 五、知识库（RAG）

```env
ZHIPU_API_KEY=               # 向量化用（embedding-3，2048 维）
ZHIPU_EMBEDDING_MODEL=embedding-3
ZHIPU_EMBEDDING_DIMENSIONS=2048
KNOWLEDGE_UPLOAD_DIR=data/knowledge_uploads
KNOWLEDGE_SCORE_THRESHOLD=0.35   # 相似度低于此值的检索段不注入，防无关内容诱导幻觉
```

数据库需要 pgvector 扩展（compose 里的 postgres 镜像已带）。

## 六、搜索与外部服务（按需）

| 键 | 用途 |
| --- | --- |
| `ZHIPU_WEB_SEARCH_API_KEY` | 智谱联网搜索工具 |
| `YOUTUBE_API_KEY` / `YOUTUBE_PROXY_URL` | YouTube 数据/字幕（国内需代理） |
| `EXA_API_KEY` / `EXA_PROXY_URL` | Exa 语义搜索（事件钩子的检索源之一） |
| `NOTION_API_KEY` | Notion MCP（面试日报写题库等） |
| `MIHOMO_API_URL` / `MIHOMO_SECRET` | 本机代理内核控制面（默认 `http://127.0.0.1:9090`）；X 与 YouTube 的出海流量都靠它，**节点不健康时早报会空**，排查先看这里 |

## 七、运行与调优（有合理默认，一般不动）

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `AUTO_CREATE_TABLES` | true | **生产建议 false**，让 alembic 迁移成为 schema 唯一权威 |
| `SUB_WORKER_CONCURRENCY` | 2 | 子 agent Worker 并发（上限 `SUB_WORKER_MAX_CONCURRENCY`=6） |
| `MAX_CONTEXT_TOKENS` | 128000 | 上下文压缩预算，可按模型窗口调大 |
| `COMPACT_THRESHOLD_L2 / _L3` | 0.5 / 0.7 | 二级/三级压缩触发比 |
| `WORKSPACE_ROOTS` | — | 浏览器端可选择的服务器工作区根目录（逗号分隔），如 `/app` |
| `LOG_SEARCH_BACKEND` / `LOKI_*` | file | 日志检索后端；上 Loki 观测栈时切 `loki` |

## 八、安全红线

1. `AUTH_SECRET` 生产必改强随机值——仓库是公开的，默认值等于把钥匙贴在门上
2. `.env`、`twitter_cookies.json`、浏览器 storage state 都是凭据，永不入 git
3. 对外暴露只走反向代理/隧道（Cloudflare 等），`API_HOST` 保持 `127.0.0.1` 由 socat/隧道转发

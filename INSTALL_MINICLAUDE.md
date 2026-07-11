# NeuralHub for MiniClaude 压缩版安装要求

本说明面向从 GitHub 下载 ZIP/TAR 压缩包后的安装场景。压缩包只包含源码和配置模板，不包含 `.env`、运行日志、数据库数据、上传文件、`node_modules`、`venv` 或构建产物。

## 1. 系统要求

- Linux x86_64，推荐 Ubuntu 22.04+
- Docker 24+ 与 Docker Compose v2
- 可访问的 PostgreSQL 14+
- 可访问的 Redis 6+
- 至少 2 核 CPU、4GB 内存，知识库入库较多时建议 8GB+

本地源码开发还需要：

- Python 3.12+
- Node.js 20+
- npm 10+

## 2. 数据库要求

知识库检索依赖 pgvector。PostgreSQL 需要安装并启用扩展：

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

`.env` 中的 `DATABASE_URL` 示例：

```env
DATABASE_URL=postgresql+asyncpg://agent:password@127.0.0.1:5432/agent_studio
REDIS_URL=redis://127.0.0.1:6379/0
```

## 3. 必填环境变量

复制模板：

```bash
cp .env.example .env
```

至少配置：

```env
DATABASE_URL=
REDIS_URL=
AUTH_SECRET=请替换为强随机字符串
DEFAULT_PROVIDER=openai
DEFAULT_MODEL=
```

至少配置一个模型供应商：

```env
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

知识库入库需要 embedding：

```env
ZHIPU_API_KEY=
ZHIPU_EMBEDDING_MODEL=embedding-3
ZHIPU_EMBEDDING_DIMENSIONS=2048
```

飞书端使用时再配置：

```env
FEISHU_APP_ID=
FEISHU_APP_SECRET=
FEISHU_VERIFICATION_TOKEN=
FEISHU_ENCRYPT_KEY=
```

## 4. Docker 启动

```bash
docker compose up -d --build
docker compose ps
curl http://127.0.0.1:8000/health/live
curl http://127.0.0.1:8000/health/ready
```

Web UI 默认由后端服务静态资源：

```text
http://服务器IP:8000/
```

如果需要单独暴露前端端口，可以用 nginx、Caddy 或 systemd/socat 反代到 `127.0.0.1:8000`。

## 5. 本地开发启动

```bash
python -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
pip install -r backend/requirements-dev.txt

cd frontend
npm install
npm run build
cd ..

uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

开发模式前端：

```bash
cd frontend
npm run dev -- --host 0.0.0.0 --port 5174
```

生产环境不要长期暴露 Vite dev server。

## 6. 验证知识库

```bash
curl http://127.0.0.1:8000/api/knowledge/status
```

飞书知识库功能需要确认：

- 飞书应用事件回调指向 `/api/feishu/event`
- Redis 可用，用于事件去重、会话状态、上传批处理
- task queue/sub worker 正常运行，用于异步入库
- PostgreSQL 已启用 pgvector

## 7. 压缩包不包含的内容

- `.env`
- `server.log`
- `data/`
- `dist/`
- `frontend/dist/`
- `node_modules/`
- `venv/`
- 本地上传文件和知识库原始文件
- 任何 API key、Cookie、代理配置或私有订阅

这些内容需要在部署机器上自行创建或配置。

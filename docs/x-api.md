# X 舆情雷达 API 手册

对 X/Twitter 舆情的完整 REST 闭环：**搜 → 比 → 盯 → 存**。四组资源全部躲在功能开关后（`X_API_ENABLED` / `X_MONITOR_ENABLED`，默认关闭），带全局频控闸门保护共享账号。

## 认证与基础地址

所有接口都需要 Bearer token（值为 `AUTH_SECRET`）：

```bash
TOKEN="$AUTH_SECRET"
BASE="http://127.0.0.1:8000"
```

不带 token 一律 `401`。

## ① 搜索 `GET /api/x/searches`

搜最近 N 天关于某关键词的推文，返回结构化 JSON。

```bash
curl -s "$BASE/api/x/searches?q=Claude+Code&days=7&limit=10&sort=engagement" \
  -H "Authorization: Bearer $TOKEN"
```

| 参数 | 说明 | 默认 |
| --- | --- | --- |
| `q` | 关键词（必填，≤200 字符） | — |
| `days` | 只保留最近 N 天（1–365） | 7 |
| `limit` | 最多条数（1–50） | 15 |
| `type` | `Latest` 最新 / `Top` 热门 | Latest |
| `sort` | `time` 时间 / `engagement` 热度加权（赞×1 + 转×2 + 浏览×0.01） | time |

响应要点：`cached: true` 表示命中 5 分钟缓存（没真的打 X）；`rate_limited: true` 时携带已抓到的部分结果和 `retry_after`。换 `sort` 只是重排同一份结果，不额外消耗搜索额度。

## ② 对比 `GET /api/x/compare`

2–4 个词同场对比声量，逗号分隔。

```bash
curl -s "$BASE/api/x/compare?q=claude,gpt,gemini&days=7" \
  -H "Authorization: Bearer $TOKEN"
```

每个词返回：推文数 `count`、原始互动总量 `total_engagement`、加权热度 `weighted_score`、最火一条 `top_post`。某个词临时取不到会标 `unavailable: true`，不连累其他词。

## ③ 监控 `/api/x/monitors`

常驻雷达：后台按间隔自动搜索，命中阈值的推文**发飞书卡片**并入库（同一推文只报一次）。

```bash
# 创建
curl -s -X POST "$BASE/api/x/monitors" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"query": "Claude Code", "interval_minutes": 60,
       "search_type": "Top", "threshold_likes": 50}'

curl -s "$BASE/api/x/monitors" -H "Authorization: Bearer $TOKEN"          # 列表
curl -s -X PATCH "$BASE/api/x/monitors/<id>" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"enabled": false}'                                                  # 改某几项（如暂停）
curl -s "$BASE/api/x/monitors/<id>/hits" -H "Authorization: Bearer $TOKEN" # 命中记录
curl -s -X DELETE "$BASE/api/x/monitors/<id>" -H "Authorization: Bearer $TOKEN"
```

创建字段：`query`（必填）、`interval_minutes`（必填，≥15）、`days_window`（默认 1）、`search_type`、`threshold_likes` / `threshold_views`（至少一个 > 0，防告警风暴）、`enabled`。

护栏：间隔 < 15 分钟 → `422`；全局监控数超上限（20）→ `409`；双零阈值 → `422`；单个监控异常不影响轮询循环。

## ④ 导出入库 `POST /api/x/exports`

把一次搜索做成 Markdown 舆情快照（含互动数据与来源链接），写入**指定**知识库，供 Agent 检索引用。

```bash
curl -s -X POST "$BASE/api/x/exports" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"query": "Claude Code", "kb_id": "<专库id>", "days": 7, "limit": 15}'
```

- `kb_id` 必填；库不存在直接 `404`，绝不隐式建库或写错库
- 文件名由关键词决定 → 同词重导为**幂等覆盖**，库里永远只有一份最新快照
- 没搜到内容返回 `status: "empty"`，不写空文档；`limit` 上限 30 控制嵌入成本

## 错误码速查

| 状态码 | 含义 | 处理 |
| --- | --- | --- |
| 401 | 未带 / 带错 token | 检查 `Authorization: Bearer ...` |
| 404 | 监控或知识库不存在 | 检查 id |
| 409 | 监控数量达上限 | 删掉不用的监控 |
| 422 | 参数不合法（间隔过小 / 双零阈值 / days 超界…） | 按返回 message 修正 |
| 429 | 频控：5s 内连打或日额度（200 次）用尽 | 按 `Retry-After` 头等待 |
| 502 | X 上游故障（登录被拦 / 超时） | 稍后重试 |

## 保护机制

- **全局闸门**：5 秒最小调用间隔 + 每日 200 次额度（Redis 计数，Redis 故障时降级放行）
- **结果缓存**：相同搜索 5 分钟内直接复用，不打 X
- **额度打满只影响这些新接口**（429），AI 早报等存量功能不受牵连
- 对比 / 监控的多次搜索只扣额度、不过间隔闸，避免自我误杀

## 速查表

| 想干嘛 | 方法 + 路径 |
| --- | --- |
| 搜推文 | `GET /api/x/searches?q=词` |
| 比声量 | `GET /api/x/compare?q=词1,词2` |
| 建监控 | `POST /api/x/monitors` |
| 看 / 改 / 删监控 | `GET` / `PATCH` / `DELETE` `/api/x/monitors/{id}` |
| 看命中记录 | `GET /api/x/monitors/{id}/hits` |
| 存进知识库 | `POST /api/x/exports` |

# Agent Studio 审计修复总汇报（2026-07）

> 承接 [comprehensive-audit-2026-07.md](comprehensive-audit-2026-07.md)（87 条证实发现）。
> 用户挑选了一个子集，分 9 批用多 agent workflow（全程 Opus 4.8）修复。
> 每批流程：建 workflow → 门禁 agent 独立审 + 跑测试 → 主控独立复跑 + 修门禁指出的超限/回归 → commit+push。
> 分支：`claude/distracted-chaum-2240f2`。

## 一、总览数字

| 指标 | 值 |
|---|---|
| 提交数 | 9（`e38004a`→`5a952ad`，均已 push） |
| 改动量（相对审计报告 `bcc9128`） | 148 文件，+8949 / −673 |
| 新增后端测试文件 | 38 个（约 300+ 用例） |
| 前端 | 新引入 vitest+jsdom，42 用例 |
| 修复条目 | 1×P0 + 约 24×P1 + 约 22×P2 |
| 后端最终 unit | **1179 passed / 3 failed（既有基线）/ 89 skipped** |
| 前端最终 | vitest 42 passed / tsc 0 错 / vite build 成功 |

## 二、逐批成果

| 批 | 主题 | commit | 关键修复 | 测试 |
|---|---|---|---|---|
| **A** | 上下文压缩 | `e38004a` | **P0** 压缩硬切拆散 tool_use/tool_result→LLM 400/会话卡死（boundary.py 边界对齐）；token CJK 加权；断连覆盖 DB 守卫；压缩并发竞态；artifact_gc 容错+护 sessions | 34 |
| **B** | 运行时/长时稳定 | `11a7185` | abort 标志残留；WS 清理异常安全；ConnectionManager 泄漏（LoopCache LRU）；_emit 泄漏；Plan 信号/StepResult/checkpoint | 47 |
| **F** | 前端可用性 | `b78da54` | **工具审批 UI**（此前完全没有）；未知 WS 事件不再打崩会话；错误呈现；断线 resync；列表 memo+条件吸底 | 42(vitest) |
| **C** | 多 agent 协作 | `7558e8b` | readonly Bash 黑名单→白名单（隔离真生效）；dispatch 超时重抛；orchestrate 并发上限；上游失败短路；父取消联动 | 58 |
| **D** | 任务队列+存储 | `17c85b6` | 飞书 flush 先提交后清；知识心跳保活；scheduler 后台 recovery；恢复循环消 N+1；/sessions 聚合；消息主键 uuid4 | 24 |
| **E** | 记忆知识库 | `ca15ed9` | 入库幂等 upsert；PDF to_thread；知识删除 API；向量阈值；**记忆文件损坏降级**（平台级单点）；hit_count；飞书上传竞态 | 24 |
| **G** | 飞书集成 | `99ba215` | **签名校验修正**（原读错 Header 形同虚设）；Redis 降级放行；多工具审批逐卡 | 26 |
| **H** | LLM Adapter | `bad8650` | 流式 4xx 吞错→读 body；流式 usage 采集（token 不再恒 0）；Anthropic thinking 可用；CONTEXT_OVERFLOW 码 | 43 |
| **I** | API 层 | `5a952ad` | Prometheus label 基数膨胀（未匹配归 unmatched）；gunicorn 默认 workers=1+告警+文档 | 3 |

## 三、⚠️ 需你手动跟进的带外项（重要）

这些是代码已改好、但**需要你在真实环境做一次动作**才能真正生效/安全的项：

1. **D7 消息主键 alembic 迁移（`20260708_0007`）**：单测覆盖不到真库 DDL。请在真实 Postgres 上 `cd backend && alembic upgrade head` 验证一次（varchar(12)→varchar(64)，仅改元数据、无表重写）。
2. **建表 baseline 约束**：当前 alembic 迁移链**尚无覆盖全部核心表的 baseline**。补齐 baseline 之前，生产环境请**保持 `AUTO_CREATE_TABLES=true`**（勿在全新库上设 false，否则核心表不会建）。
3. **G 飞书签名上线落配**：签名是**配置门控**的——`common/feishu_signature.verify_signature` 在 `verification_token`/`encrypt_key` 均为空时返回 True（放行）。上线后必须在**飞书开放平台**确认这两个值并写入后端 env，否则鉴权代码正确但**安全收益为零**（仍无鉴权）。
4. **H thinking/usage/超限 需真 provider 验证**：thinking 需真 Anthropic key 验签名多轮；usage 需真流式帧核对字段；CONTEXT_OVERFLOW 关键词需按真实 provider 措辞增补（措辞不同会保守回落 API_ERROR）。

## 四、你有意排除、仍未修的项（需另行决定）

审计报告里的这些**没做**（你的挑选清单未包含，多为改到线上鉴权/部署的安全项）：

- **P0-1 `/v1/chat/completions` 完全无鉴权**（公网可匿名驱动付费 Agent + RCE 面）— 一行 `dependencies=[Depends(verify_token)]` 即可，建议尽快自行加。
- **P0-3 权限默认不安全**（Bash 等内置工具默认免审批）— 安全面较大。
- 默认 `auth_secret` 强校验、`/reports` 存储型 XSS、knowledge_uploads 磁盘无限增长、§5.2 PENDING 永久脱节、多数前端/飞书/adapter P2。

> 注：C 批已把 readonly **子 agent** 的 Bash 改成白名单（隔离生效）；但 P0-3 指的是**主 agent** 的内置工具默认免审批，仍未动。

## 五、遗留的非阻断技术债（门禁记录，可后续清理）

- `feishu_handler.py`(520)、`s05_skills/runtime.py`(290)、`websocket.py`(497) 等**既有超 200 行**文件未拆分（本次只保证不显著恶化，`openai_support.py` 已顶到 200）。
- `feishu.py::_seen_by_handler`（菜单去重路径）同样缺 try/except（G1 只覆盖了消息主链路）。
- `CONTEXT_OVERFLOW` 错误码目前**只产不消**，需上层压缩/重试模块接入才有实效。
- Anthropic thinking：`_assistant_message` 未过滤空 signature 块（跨 provider replay 边缘场景可能 400）。
- E 入库幂等是**应用层** check-then-act，并发双插仍需 DB `(kb_id,filename)` 唯一约束（迁移）兜底。
- 真正支持多 worker 需给内存单例接 Redis pub/sub 缓存失效。

## 六、既有非回归基线（不是本次引入，勿误判）

- `test_executor_card.py` ×3 失败：其 mock 只桩 `.complete` 未桩 `.stream`，命中流式路径 `streaming.py`。属 s07_task_system，需单独修（给 mock 补 `.stream` 异步生成器）。
- `test_auth.py` 偶发 teardown flake（asyncpg 事件循环拆卸竞态），隔离跑通过。

---
*修复方式：9 批多 agent workflow，全程 Opus 4.8，逐条门禁独立验证 + 主控复核。完整逐项证据见各 workflow 运行记录。*

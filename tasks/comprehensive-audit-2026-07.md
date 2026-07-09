# Agent Studio 全面审计与改进方案（2026-07-07）

> 方法：13 个维度审查 agent 并行扫描 backend/ + frontend/，每一条发现再由独立的
> 证伪 agent（Opus 4.8）逐条对照真实代码验证。共产出 **87 条已证实发现**
> （3× P0 / 32× P1 / 52× P2），另有 7 条被证伪剔除（见附录，避免误导）。
> 每条都带「可落地的具体改法」，并已吸收证伪 agent 对改法可行性/副作用的复核意见。
>
> 严重性定义：**P0**=丢数据/远程执行/公网 DoS；**P1**=功能错误或长时间运行后退化；
> **P2**=可用性、体验、加固与技术债。

---

## 0. 结论速览

| 主题 | 最严重问题 | 数量(P0/P1/P2) |
|---|---|---|
| **上下文压缩** | 压缩硬切拆散 tool_use/tool_result → LLM 400、会话永久卡死（P0） | 1 / 5 / 2 |
| **记忆与知识库** | 入库无幂等+无心跳，崩溃重试成批重复入库；记忆文件损坏拖垮全平台 | 0 / 3 / 5 |
| **多 agent 协作** | readonly 子 agent Bash 黑名单大量漏网，只读隔离形同虚设 | 0 / 1 / 7 |
| **长时稳定性** | 会话/任务表永不清理、内存单例只增不减，运行数周后线性退化直至不可用 | 0 / 7 / 14 |
| **可用性（前端/飞书/adapter/API）** | Web 端无审批 UI、错误不呈现、断线不补偿；飞书签名形同虚设 | 0 / 16 / 21 |
| **安全（横切）** | `/v1/chat/completions` 公网无鉴权 + Bash 默认免审批 = 匿名 RCE（P0×2） | 2 / — / — |

**三条必须最先处理的 P0：**
1. `/v1/chat/completions` 完全无鉴权 —— 结合 Cloudflare 公网暴露，匿名即可驱动付费模型、
   套取系统提示，并因 Bash 默认免审批而形成远程命令执行面。
2. 上下文压缩按「最近 N 条」硬切，约 50% 概率拆散工具调用配对 → LLM 返回 400 →
   会话被污染后每次重试都 400，**除非 reset/换设置/重启否则永久不可用**。
3. 权限默认策略不安全：`SecurityPolicy.dangerous_tools` 是死字段，Bash/file_write/file_edit
   等副作用工具默认 `requires_approval=False`，人工审批链路对它们永不触发。

> 与简历自评一致的一点：s09/s10/s03/s11/s12/permissions 六个子系统确认为 0 字节空壳，
> 「13 子系统中仅 7 个真正落地」得到代码层面证实（详见 §6）。

---

## 1. P0 —— 立即修复

### P0-1　`/v1/chat/completions` 公网无鉴权（匿名驱动付费 Agent + RCE 面 + DoS）
`backend/api/routes/chat_completions.py:22`

**问题**：该路由 `APIRouter(tags=["completions"])` 无任何鉴权依赖，`app.py:156` 裸 include，
全局也没有鉴权中间件；而 8 个兄弟管理路由（providers/sessions/logs/metrics/mcp/workspaces/
knowledge/provider_roles）统一挂了 `dependencies=[Depends(verify_token)]`，唯独这个 OpenAI
兼容端点漏掉。匿名请求可自选 provider/workspace/permission_mode 与完整 messages（system 角色
被保留），因此可：① 免费驱动付费模型、提示注入套取系统提示与工具清单；② 每次触发
`MCPToolBridge.sync_all()` 连 MCP；③ 因 Bash/Write/Edit 默认 `requires_approval=False`
（见 P0-3），在自带 workspace 下直接命令执行。需人工审批的 MCP 工具则会在
`wait_tool_approvals` 挂满 300s（`agent_loop.py:95`）占用连接/会话资源。

**改法**（最小必做 + 强烈建议叠加）：
1. 给该 router 加 `dependencies=[Depends(verify_token)]`，与兄弟路由一致。`settings.py:36`
   的 `auth_secret` 默认非空，verify_token 立即生效；后端无内部调用方使用该端点，
   不会回归——唯一影响是外部 OpenAI 客户端需开始带 `Authorization: Bearer <secret>`（预期收敛）。
2. 若要保留公开网关语义：改独立 API-Key 校验，并**强制 `workspace=None`、锁定 permission_mode**，
   使 Bash/Write/Edit/dispatch 等副作用工具不被注册。
3. 无人值守 HTTP 上下文把审批超时调到极小或对需审批工具直接快速失败，杜绝 300s 挂起。

### P0-2　上下文压缩硬切拆散 tool_use/tool_result 配对 → LLM 400 → 会话永久卡死
`backend/core/s06_context_compression/compressor.py:54`、`level3_summary.py:35`、`compressor.py:171`

**问题**：`ContextCompressor.compact`、`level3_summary.summarize_archive`、
`_build_fallback_messages` 三处都把非 system 消息按固定条数（reserve=6）切成 old/recent，
**不检查切分点是否落在 assistant(tool_calls) 与 tool(tool_results) 之间**。agent 每轮固定追加
assistant+tool 两条，边界约半数落在 tool 消息上：配对的 assistant 被折叠进摘要，recent 首条
变成孤儿 tool_result。转换层（`anthropic_support.py:60`、`openai_support.py:61`）会产出无前置
tool_use 的 tool_result → **Anthropic/OpenAI 均 400**。更糟：`agent_loop_run.py:60-72` 用
`messages[:]` 就地改写了内存历史，孤儿结构残留，本轮抛错后用户重发消息仍带孤儿 →
**每次 run 都 400**；且 `ConnectionManager` 按 session 缓存被污染的 loop，压缩后 token 已低于阈值
不会再触发自愈。实时 run 路径不调用 `sanitize_message_history`，故须换模型/换设置/清会话/重启才恢复。

**改法**：
1. 在 s06 内新建 `boundary.py`，抽公共函数 `align_boundary(non_system, reserve)`：
   `while recent and recent[0].role == "tool": 把 recent[0] 移入 old`（本库每轮 assistant 只对应
   一条聚合 tool 消息，检查 recent[0] 即可，稳妥起见再校验其 tool_call_id 能否在 recent 的
   tool_calls 中找到）。old 只渲染成摘要文本、无配对约束，安全。
2. `compressor.py:54`、`compressor.py:171`（fallback）、`level3_summary.py:35` **三处**都改用它。
   注意 `compressor.py` 已 189 行，helper 必须放新文件避免破 200 行红线。
3. 纵深防御：在 `build_llm_request`/run 入口对历史调一次 `sanitize_message_history`，让已被污染的
   存活会话也能自愈（否则老会话仍需 reset）。
4. 补单测：构造 assistant/tool 交替序列，断言压缩后所有 tool_result.tool_call_id 都能在保留消息的
   tool_calls 中找到。

### P0-3　权限默认策略不安全：Bash 等内置工具默认免审批
`backend/core/s02_tools/security_gate.py:111`

**问题**：本应承载权限的 `backend/core/permissions/` 是 4 个空文件；真实防线只有
`SecurityGate._reject_reason`，它只查工具存在性/allowed_tools/max_calls/requires_approval 四项。
`SecurityPolicy.dangerous_tools`（`common/types/security.py:12`）定义后从未被读取，全库唯一引用是
`agent_loop.py:71` 传入空列表。`ToolPermission.requires_approval` 默认 False，内置工具无一设 True
（仅 MCP 桥接工具在 `tool_bridge.py:134` 强制 True），即 Bash/file_write/file_edit 全部自动签名执行。
Bash 内部危险命令拦截只有 3 条正则（`rm -rf /`、`mkfs`、`dd`），`rm -rf ~`、`curl … | sh` 全放行。
对一个经飞书对外服务的常驻后端，提示注入即可在宿主机执行任意命令。

**改法**（②+③ 打底，Bash 本体加固为主）：
1. **②给 bash/file_write/file_edit 的 ToolDefinition 显式设 `requires_approval=True`**，复用现成的
   `pending_approval→review_tool_approvals→wait_tool_approvals` 链路与飞书/WS 审批卡片。
   ⚠️回归面：plan runner、s04 子代理、s07 executor 依赖 Bash/Write 做无人值守自治，强制审批会打断
   它们 —— 需对这些**受信内部上下文**走 `allowed_tools`/auto-approve 白名单放行，仅对外部入口审批。
2. **③删除/实现空的 `permissions/` 模块**，消除误导。
3. 让 `dangerous_tools` 变「活」：给默认值（如 `["Bash"]`）并在 `_reject_reason` 中读取；同时把
   Bash 从对外的飞书注册表移除或经 `allowed_tools` 显式收窄，用真实沙箱（受限 PATH/env、禁网、
   jail cwd）+ 命令 allow/deny 策略替换 3 条正则。
4. 回归重点：审批超时默认拒绝路径 + 自治流程不被审批阻断。

---

## 2. 上下文压缩（Context Compression）

> 除 P0-2 外，本子系统还有 7 条：核心矛盾是「压缩只该影响发给 LLM 的上下文，却多处
> 污染/删除了持久化的原始历史」，以及「中文场景 token 估算严重失真导致压缩时机全错」。

- **P1｜断连时用压缩后的内存历史整表覆盖 DB，原始历史永久删除** ·
  `backend/api/routes/websocket.py:98`
  `_sync_messages` 在 disconnect/clear/设置变更三入口把已压缩为 `[system, 摘要, 最近6条]` 的
  `loop.messages` 交给 `save_messages`，而后者**先 DELETE 整个 session 的消息再重写**。只要会话触发过
  压缩，用户断开的瞬间 DB 完整历史就被摘要版覆盖，重开只剩一条「[对话历史摘要]」，走 0.9 路径时
  连无损备份都没有。**改法**：当 `has_checkpoint_fn` 为真且 checkpoint 未失败时直接 return
  （与 `websocket_support.py:199` run_loop finally 块的既有守卫一致，约 3 行）；DB 由 checkpoint
  逐条追加维护。`feishu_handler.py:451`、`s07_task_system/executor.py:242` 有同型调用，一并排查。

- **P1｜token 估算 `len//4` 对中文低估 3–8 倍 + 上限硬编码 180000** ·
  `backend/core/s06_context_compression/token_counter.py:11`
  中文 1 字≈1 token 但被当 0.25 token 估。阈值又硬编码 180k、不随模型（gpt-4o 128k 模型上
  `0.9×180k=162k` 估算值真实早已溢出）。中文长会话在达到压缩阈值前就已上下文溢出，且溢出后
  `run_agent_loop` 直接置 error 并 raise，无「收到 context 超限就强制压缩重试」的兜底，超长历史
  留在内存和 DB → 每条新消息重复同一 400。**改法**：① `token_counter.py` 与 `level1_artifact.py:22`
  按 Unicode 区间给 CJK 字符加权（纯标准库）；② `max_context_tokens` 进 `settings.py`（照搬
  `compact_threshold_l2/l3` 的现成注入模式），保守默认 128000；③ **更稳的替代**：
  `agent_loop_support.py:166` 已解析出上一轮真实 `usage.prompt_tokens`，把它回灌进压缩决策，
  从根上消除估算误差（无需 tokenizer 依赖）——但注意流式路径 usage 目前恒为 0，需先修 §5 的
  adapter usage 采集。

- **P1｜`artifact_gc` 按 mtime 7 天无差别删除 `data/sessions`，L3「无损备份」失效** ·
  `backend/core/s06_context_compression/artifact_gc.py:19`
  L2/L3 把工具结果替换成 `data/artifacts/…`、`data/sessions/…` 路径并永久留在历史，系统提示还引导
  模型 `read_history` 回查原文；但 GC 7 天后无条件删除，模型只会拿到「History file not found」，而这
  正是唯一无损副本。**改法**：① 把 `data/sessions` 移出 `DEFAULT_ROOTS` 或给远长保留期（一行，先止血）；
  ② `RETENTION_DAYS` 提为 settings 配置并在摘要文案注明保留期；③ 引用检查经 `sub_worker.py` 注入
  `referenced_paths_provider` 回调（core 不直接 import storage，守 CLAUDE.md 分层），或用 LRU 语义
  在 `read_history` 命中时 `os.utime` 刷新 mtime。⚠️另需 docker-compose 给 app 与 sub-worker 挂**共享
  data 卷**，否则容器重建照样全丢。

- **P1｜压缩 await 期间整表切片覆盖，与同 session 并发 run 竞态丢消息** ·
  `backend/core/s01_agent_loop/agent_loop_run.py:60`
  `messages[:] = await compressor…` 基于 await 前的快照整体覆盖内部列表；而 `websocket.py:258` 不检查
  已有 run 是否结束就 `create_task(run_loop)`，同一 loop 可并发跑两个 run（无锁，对比 feishu 有
  `_chat_lock`）。run A 摘要期间 run B append 的新消息会被 A 覆盖丢失。**改法**（三层，按顺序）：
  ① 把 `websocket.py:145` 的 busy 判断改为 `task and not task.done()`（一行、立即封住单连接，
  当前状态集合漏了 `compacting`/`waiting_approval`）；② AgentLoop 加 `self._run_lock = asyncio.Lock()`
  兜住跨连接 TOCTOU；③ 差量写回 `snapshot_len=len(messages); messages[:]=compacted+messages[snapshot_len:]`
  作第三层保险。顺带修 `websocket.py:271` 覆盖 task 句柄导致 abort 失效。

- **P1｜artifact GC 循环遇任意文件异常即永久死亡，且只挂在 sub_worker** ·
  `backend/core/s06_context_compression/artifact_gc.py:46`
  遍历间隙文件被并发删除/权限不足 → `FileNotFoundError`/`PermissionError` 冒泡 → 协程结束，
  `sub_worker.py:79` create_task 后不检查存活、无重启，GC 静默停摆到重启。且主 API 进程（真正写归档者）
  完全没接 GC。**改法**：① `_cleanup_root` 对每文件 stat/unlink 包 `except OSError: continue`；
  ② 循环体包 try-except 记日志后继续下一轮（参照 `_recover_loop`）；③ 在 API lifespan 也启动 GC；
  ④ 目录路径用共享卷方案（见上）或全链路联动 `read_history` 的 `ALLOWED_ROOTS`。

- **P2｜L2 归档不保护最近消息**：`level2_compact.py:19` 可能把模型尚未读过的最新工具结果立刻替换成
  摘要。改：`compact_oldest_large_tool_result` 仅在 `messages[:-RECENT_KEEP_COUNT]` 内找可归档结果。
- **P2｜无增量摘要，L3 反复触发信息逐轮衰减**：`level3_summary.py:96` 把上轮摘要截断到 1200 字符重摘。
  改：识别 `[对话历史摘要]` 开头的消息豁免 `_clip`，做增量式「新摘要=旧摘要+新增历史」；并统一两套
  阈值（0.9 的 ContextCompressor 与 L3）避免两种摘要消息并存。

---

## 3. 记忆与知识库（Memory & Knowledge）

> 长期记忆（`experiences.json`）与知识库（s13 向量检索）两条线都存在「无幂等/无淘汰/无删除」
> 的共性问题，长期运行必然重复污染 + 磁盘膨胀；且记忆文件损坏是**平台级单点故障**。

- **P1｜知识入库无幂等 + 无心跳续租，超时/崩溃重试成批重复入库** ·
  `backend/api/routes/knowledge.py:104`
  入库任务 `max_retries=1, timeout=3600` 提交，却走 `task_queue_consumer.py:61` 早退分支**跳过心跳续租**，
  lease 固定 claim+3600s。超长批次或 worker 崩溃后 `recover_stale_task_payloads` 重新入队，而
  `KnowledgeIngestor.ingest` 每次无条件 `create_document`（不按 kb_id+filename 去重）→ 文档与向量成倍
  重复，检索 top_k 被同一内容霸占；lease 中途过期还会两个 worker 并发双跑同批。**改法**（组合）：
  ① `knowledge.py:112` `max_retries` 改 0（止血，与飞书路径一致）；② 知识分支纳入 `_heartbeat_loop`
  （提取到 `task_queue_consumer_helpers.py`，避免破 200 行）；③ **根治=幂等**：`KnowledgeStore` 增
  `get_document_by(kb_id, filename[, hash])`，命中则借 `kb_chunks.doc_id` 的 `ondelete=CASCADE` 删旧
  chunk 后覆盖（upsert），并加 `(kb_id, filename)` 唯一约束兜并发。补「重放同批不翻倍」单测。

- **P1｜上传文件永不清理，`data/knowledge_uploads` 磁盘无限增长** ·
  `backend/api/routes/knowledge_upload.py:33`
  每次上传写至多 500MB 到 `frontend/{task_id}/`，入库后无论成败都不删；`artifact_gc` 的
  `DEFAULT_ROOTS` 也不覆盖它。**改法**：① `run_local_knowledge_ingest_payload` 的 finally 里
  `shutil.rmtree(Path(file.path).parent, ignore_errors=True)`（rmtree 前校验位于
  `knowledge_upload_dir/frontend` 下防误删）；飞书路径 finally `unlink` 单文件；
  ② 兜底把 `data/knowledge_uploads` 加进 `DEFAULT_ROOTS` 按 7 天回收；③ `save_upload_batch` 的
  except 分支也 rmtree 本次目录（413 中途落盘的文件）。

- **P1｜PDF/DOCX 同步解析跑在事件循环上，大文件冻结整个进程** ·
  `backend/core/s13_knowledge/ingest.py:27`
  `async ingest` 内直接调同步 `parse_document`（pypdf 逐页 extract，20MB 复杂 PDF 数十秒纯 CPU）。
  在 sub_worker 里会**阻塞心跳续租** → 其他 sub-agent lease 过期被重复执行；在 API 主进程里则所有
  WS/飞书/HTTP 无响应。**改法**：封装 `_parse_and_split(path)` 同步函数，改
  `chunks = await asyncio.to_thread(_parse_and_split, request.file_path)`（标准库，守 core 约束）。
  受 GIL 限制不能并行加速，但每 ~5ms 抢占切换足以让心跳/ping 恢复调度、消除假死与 lease 过期；
  彻底隔离 CPU 可后续升级 ProcessPoolExecutor。

- **P2｜记忆文件损坏 → 所有 loop 创建失败（平台级单点）** ·
  `backend/storage/memory_store.py:20` / `s05_skills/runtime.py:276`
  `_build_memory_index` 无降级：`experiences.json` 手改出错/损坏时 `MemoryStore.load` 抛
  `MEMORY_STORE_LOAD_ERROR`，导致所有会话/子 agent/定时任务的 loop 创建全部失败。**改法**：
  `_build_memory_index` try-except 降级为 `MemoryIndex(LongTermMemory())`；`load` 内解析失败时把坏文件
  改名 `.corrupt` 留档并返回空；`save` 改「写 .tmp 后 `os.replace`」原子替换（参照同目录
  `user_config_store.py`）。

- **P2｜长期记忆写回未接线，`hit_count` 只在内存自增从不持久化** ·
  `backend/core/s06_context_compression/memory_index.py:21`
  召回权重形同虚设，且每次 `match` 无条件 +1（重复 query 也累加）。**改法**：短期移除自增或每
  `(session, entry_id)` 只计一次；接线写回时在会话正常结束处经 `MemoryStore.add` 落盘，`add/save` 内
  做容量淘汰（按 created_at+hit_count 保留上限 N=500）并用单写者队列避免并发 load-modify-save 丢更新。

- **P2｜知识库无删除能力，误传/重复内容永久污染检索** · `backend/core/s13_knowledge/store.py:23`
  改：增 `delete_document(doc_id)`（chunk 由 FK CASCADE 清）与 `delete_base(kb_id)`（`kb_chunks.kb_id`
  无 FK，需先按 kb_id 删 chunk 再删库）；service 转发；`knowledge.py` 加 `DELETE /bases/{kb_id}`
  与 `DELETE /documents/{doc_id}`，前端补删除入口。
- **P2｜向量检索无相关性阈值，无关提问也注入 top_k 段诱导幻觉** · `backend/core/s13_knowledge/service.py:124`
  改：`hits = [h for h in hits if h.score >= settings.knowledge_score_threshold]`（embedding-3 余弦先取
  0.35~0.4）；过滤后为空自然走 empty_reply；把 score 透出到来源注脚便于调阈值。
- **P2｜飞书批量上传 flush 与 rpush 竞态丢文件** · `backend/api/routes/feishu_knowledge_upload_batch.py:76`
  改：把「读取+清空」用 Redis pipeline(MULTI) 的 `LRANGE+DEL` 或循环 `LPOP` 取完再删，做成原子操作。

---

## 4. 多 Agent 协作（Sub-agents & Teams）

> 隔离与失败传播是重灾区；且「团队协作（s09/s10）」整层是空壳，文档却宣称已具备（见 §6）。

- **P1｜readonly 子 Agent 的 Bash 黑名单大量漏网，只读隔离形同虚设** ·
  `backend/core/s04_sub_agents/permission_policy.py:74`
  系统提示承诺「不能修改/创建/删除文件」，但 `is_readonly_blocked` 用正则黑名单，实测放行
  `touch/dd(of=)/curl -o/wget -O/find … -delete/truncate/ln/install/rsync/tar -x/unzip/git apply/包管理器
  install` 等。子 agent 常处理外部不可信内容（web/x/youtube 结果），提示注入即可在「只读」模式写盘。
  **改法**：改**白名单放行**——只读命令前缀集合（ls/cat/head/tail/wc/grep/rg/find(排除 -delete/-exec)/
  stat/diff/git 只读子命令…），首 token 不在白名单即拒；对 `; | && ||`（及换行、`&`、`$()`/反引号）
  **拆段逐一校验**；读写双用命令加参数守卫（find 拒 -delete/-exec、curl/wget 拒 -o/-O、tar/unzip 拒
  -x）。可复用 `bash.py` 已有的 `_split_command_tokens`/`_normalize_token`/`_resolve_exec_token`，
  与 `permission_policy` 共用一个健壮分段器，顺带修掉 bash.py 只检查首段的既有局限。

- **P2｜orchestrate_agents 单阶段并行无并发上限** · `backend/core/s04_sub_agents/orchestrator.py:69`
  可一次并发拉起大量子 agent + shell 耗尽资源。改：`OrchestratorConfig` 加 `max_parallel_agents`
  （默认 5），`_run_stage` 用 `asyncio.Semaphore` 包裹 `run_isolated_agent`。
- **P2｜上游子任务失败后，错误文本被当依赖结果注入下游** · `backend/core/s04_sub_agents/orchestrator.py:46`
  改：维护 `failed_roles`，下游若依赖失败角色则短路为 is_error 结果，或注入时显式标注
  `[来自 X 的结果-执行失败]`；`previous_outputs` 只存成功结果。
- **P2｜父任务取消时已入队的 spawn_agent 子任务不联动取消** · `backend/core/s02_tools/builtin/spawn_agent_wait.py:52`
  改：给 `TaskQueue` 增 `cancel(task_id)`（PENDING 移出队列置 FAILED，RUNNING 写取消标记，sub_worker
  每轮/心跳检查并中止 loop）；spawn_agent 捕获 CancelledError 时批量 cancel。
- **P2｜dispatch_agent 超时分支不可达** · `backend/core/s04_sub_agents/lifecycle.py:23`
  `spawn_and_run` 把 CancelledError 吞成 AgentError，`wait_for` 超时永远走不到超时消息分支。
  改：`except asyncio.CancelledError` 分支 `loop.abort()` 后 `raise`（原样重抛）。

---

## 5. 长时稳定性（Runtime / TaskQueue / Storage）

> 这是「长时间流畅性」的核心：**多处内存单例只增不减、多张表永不清理、多个后台循环遇异常
> 永久静默死亡**。单看每条都不致命，叠加起来就是「跑几周越来越慢直到 OOM/超时」。

### 5.1 运行时（Runtime）
- **P1｜`ConnectionManager._loops/_loop_settings` 断连后永不回收** · `backend/api/routes/websocket.py:48`
  `disconnect()` 只清 `_connections`；`_loops` 只在 `clear_session()`（仅 DELETE 会话时调用）移除。
  每个新 session 的 AgentLoop（持完整历史+ToolRegistry+MCP 桥+compressor）进程内常驻，用户不断新建
  会话 → 内存只增不减。**改法**：给 `_loops` 加 **LRU 上限或空闲 TTL 逐出**（借鉴
  `feishu_menu_state.py` 的 TTL 模式，不依赖连接状态即可封顶内存）；并在 run_loop 的 done_callback
  里若连接已断则 sync+abort+pop，覆盖「断连时任务仍在跑」的泄漏路径。
- **P1｜abort 后 `_aborted` 标志残留 → 下一条消息必报 LOOP_ABORTED** · `backend/core/s01_agent_loop/agent_loop_run.py:43`
  abort 用 `task.cancel()` 抛 CancelledError 绕过 `except Exception`，标志不被消费。**改法**（主修）：
  run 开头改为只 `loop._aborted = False` 清零、**不再抛错**（中途 abort 已由 `:175` 检查+cancel 覆盖）；
  **必须同步改 `test_agent_loop.py:112` 那条固化了 bug 行为的断言**。补强：`except BaseException` 分支执行
  `patch_orphan_tool_calls`+`checkpoint_from` 后原样重抛，修补取消路径的孤儿历史。
- **P1｜WebSocket 断开清理不具异常安全性，泄漏订阅任务/Redis 连接** · `backend/api/routes/websocket.py:363`
  泛化异常分支 send_json 失败即 return 不 disconnect；`disconnect()` 第一步 `await _sync_messages` 抛错则
  后续 cancel/pop 全跳过。每次泄漏一个 asyncio 任务 + 一条 pubsub 连接，长期耗尽 Redis 连接数。
  **改法**：给整个 `ws_endpoint` 主体套 try/finally，finally 内只调一次 `disconnect`（替换两处重复调用）；
  `disconnect()` 内把同步清理（pop+cancel）前移到 `_sync_messages` 之前，`_sync_messages` 单独 try-except。
- **P2｜`_emit` 用 `asyncio.ensure_future` 派发事件，任务无引用、异常永不回收** · `backend/core/s01_agent_loop/agent_loop.py:101`
  流式场景 fire-and-forget 任务无界堆积。改：`self._pending_events: set[Task]`，add + `add_done_callback`
  discard 并记录异常。
- **P2｜PlanControlStore 的 stop/pause 信号文件应用后不清除** · `backend/core/s01_agent_loop/plan_execute_runner_steps.py:86`
  污染同 session 后续执行/恢复。改：应用后 `PlanControlStore().clear(session_id)`，`run()`/`resume_run()` 开头统一 clear。
- **P2｜Plan checkpoint 全目录同步扫描在事件循环上，且非终态文件永不清理** · `backend/core/s01_agent_loop/plan_checkpoint_store.py:69`
  改：cleanup 删超龄非终态文件（mtime>30 天）；`websocket.py` 调用处 `await asyncio.to_thread(...)`。
- **P2｜StepResult 按 session 而非 plan 存储，新计划注入上个计划的步骤结果** · `backend/core/s01_agent_loop/plan_execute_runner_steps.py:49`
  改：存储路径加 plan 维度 `base/session_id/plan_name`，或 `_reset_state` 后按 plan 隔离。

### 5.2 任务队列（TaskQueue）
- **P1｜投递(Redis)与持久化(PG)可永久脱节，PENDING 丢失后无自愈** · `backend/core/task_queue.py:51`
  claim 先 brpop 再 `persistence.claim`，中途 DB 故障/SIGKILL → task_id 已出队但 DB 仍 PENDING；
  Redis 重启/queue TTL 24h 过期同样留下孤儿 PENDING，而恢复循环只处理 RUNNING+lease 过期。父 agent 只能干等
  `global_timeout`。**改法**：① claim 里 `persistence.claim` 包 try-except，异常先 `lpush` 回队再抛；
  ② `recover_stale_task_payloads` 对超宽限期的 PENDING 用 `lpos`/`lrange` 查是否在队列，不在则重排
  （PG claim 用 `FOR UPDATE SKIP LOCKED` 且只认 PENDING，重复入队幂等安全）。
- **P1｜飞书批量 flush 先清空 Redis 批次再提交，提交失败静默丢文件** · `backend/api/routes/feishu_knowledge_upload_batch.py:82`
  改：改「先 `await submit_ingest_batch` 成功再 `_clear_batch`」；`_send_chat_text` 单独 try-except；
  失败路径重新 arm 一次 `_delayed_flush`。注意 `TaskQueue.submit` 对 list 用无条件 lpush 不天然幂等，
  幂等需在 submit 内加 `sismember` 去重守卫。
- **P1｜知识入库任务游离在心跳体系外，worker 重启/超长批次重复入库** · `backend/api/task_queue_consumer.py:55`
  （与 §3 第一条同源）**改法**：knowledge 分支外层加 `heartbeat=create_task(_heartbeat_loop)`+finally cancel；
  ⚠️不要用 `helpers._timeout_seconds`（它读 input_data，对 knowledge 恒返回默认 120s 会误杀 3600s 任务），
  要用 `payload.timeout_seconds`；**根因仍在幂等**（心跳只解决 lease 过期，真崩溃后仍重跑，须叠加 upsert）。
- **P1｜TaskScheduler 启动时串行内联执行错过的定时任务，阻塞 FastAPI 启动最长每任务 10 分钟** · `backend/core/s07_task_system/scheduler.py:37`
  服务在任一调度时刻后重启即同步跑任务、`/health` 全不通 → K8s 探针超时杀进程 → `last_run_at` 只在执行后写
  → **崩溃重启循环 + 重复推送**。**改法**：`start()` 里把恢复改为后台
  `self._recovery_task = asyncio.create_task(self._recover_missed_tasks())`（引用存实例防 GC，stop() 一并 cancel）；
  `acquire_running` Redis 锁已能去重，后台并发安全。
- **P2**（同源退化，与 P1 互补）：恢复循环每 30s 全表扫描子任务表（`task_queue_support.py:52`）；
  artifact GC 同步扫描阻塞循环+异常静默死亡（`artifact_gc.py:30`）；wait 超时把滞留 PENDING 当终态返回、
  之后仍被 worker 捡起成僵尸（`task_queue_support.py:173`）。

### 5.3 存储（Storage）
- **P1｜恢复循环每 30s 对永不清理的 `sub_agent_tasks` 表做全表 N+1 扫描** · `backend/storage/sub_agent_task_store.py:100`
  取全表 id 再逐个 db.get，无删除路径。累积 5 万任务即每 30s ~5 万查询。**改法**：① 新增
  `list_stale_running(now)` 一条 SQL 过滤（`status=='running' and 0<lease_expires_at<now`，命中现有索引，
  稳态零行）；持久化分支用它、Redis-only 分支保留 smembers。② 新增 `purge_finished(before_ts)` 每天清理
  终态旧行（建议补 `(status, created_at)` 复合索引，保留期 7 天）。
- **P1｜`GET /api/sessions` 每次全量加载所有会话的全部消息** · `backend/storage/session_store.py:58`
  `list_all` 用 `selectinload(messages)` 把整张 messages 表载入内存并反序列化 tool_*_json，路由却只用
  `len()`；而每个子 agent 都建一个 `sub-agent:{task_id}` 会话且永不清理。**改法**：改聚合计数
  `select(SessionRecord, func.count(MessageRecord.id)).outerjoin(...).group_by(SessionRecord.id)`；
  列表 `where id.notlike('sub-agent:%')` 排除 checkpoint 会话；子任务终态 N 天后定期
  `delete(SessionRecord).where(id.like('sub-agent:%'))`（CASCADE 级联删消息）。
- **P2｜建表 create_all 与 alembic 双轨，多次漏迁移 + 多进程并发 init_db 建表竞态** · `backend/storage/database.py:54`
  改：autogenerate 一个覆盖当前全部 model 的 baseline 迁移放链头；`init_db` 加 `auto_create_tables` 开关，
  生产默认关（entrypoint 已跑 alembic），sub_worker 只做连接性检查。
- **P2｜`run_traces` 只写不清理、query 无 LIMIT** · `backend/storage/run_trace_store.py:44`
  改：加 `purge(before)` 由日常清理循环按 30 天调用；query 加 `limit=500` 默认倒序。
- **P2｜消息主键是 12 位十六进制随机串（48 bit）且全表全局主键，长期碰撞致整批写入失败** · `backend/storage/models.py:36`
  改：alembic 把 `messages.id` 扩为 String(64)（PG 上仅改元数据），`generate_id` 返回 `uuid4().hex`；
  注意 ToolCall.id/ToolResult.tool_call_id 同源需一并核对。
- **P2｜LoginWorkflowStore 锁字典只增不减 + create_workflow check-then-act 竞态** · `backend/storage/login_workflow_store.py:46`
  改：workflow 结束时 pop 锁或改按 user_id 固定锁；create 改单事务 `SELECT … FOR UPDATE`。

---

## 6. 可用性与适用性（Frontend / 飞书 / Adapter / API）

### 6.1 前端（Web 端）
- **P1｜Web 端完全没有工具审批 UI，MCP 工具调用必然卡 5 分钟后被自动拒绝** · `frontend/src/lib/websocket-normalize.ts:40`
  `tool_approval_required` 事件不被识别 → 落兜底转成 error 打成错误态；全前端无发送 `tool_approve/tool_reject`
  的代码。后端接收侧已就绪（`websocket.py:330`），只需补前端。**改法**：normalize 加
  `tool_approval_required` 分支透传 tool_calls/timeout；sessionStore 加 `pendingApprovals`，
  MessageList/ToolCallLine 渲染批准/拒绝按钮 `agentWs.send({type,tool_call_id})`；⚠️审批期间
  （`waiting_approval`）暂停 90s 的 `TOOL_RESULT_TIMEOUT`，否则合法审批被前端提前打成 error。
  `useWebSocket.ts` 已 271 行，审批处理抽独立 helper。
- **P1｜未知 WS 事件一律归一化为 error，`sub_agent_*` 等正常事件把会话打成错误态并丢工具结果** · `frontend/src/hooks/useWebSocket.ts:235`
  改：normalize 兜底改为「仅当 `raw.type==="error"` 才 error，否则返回中性 `{type:"ignored"}`」（emit 对无
  处理器的 type 是空操作，无需额外 handler），并扩 `WsIncoming` 联合类型；`onError` 保留真实 error 的
  flush 语义。
- **P1｜WS 断线重连后不做状态补偿，3 次失败后静默死亡，UI 永久卡运行态** · `frontend/src/lib/websocket.ts:126`
  改：`on("open")` 区分首连/重连（带 `reconnected` 标志，避免首连就覆盖乐观消息）后走**非破坏性 resync**
  （拉临时变量、成功才替换，失败保留旧 messages）；重试上限改无限+封顶退避≤30s，放弃时 emit 事件由 store
  显示手动重连横幅；后端(重)连时对 direct 模式也下发一次 loop 状态快照（否则硬重启后终态缺失，纯前端 refetch 无效）。
- **P1｜后端错误从不呈现给用户，onError 只写 console，错误文本又被 compact 模式隐藏** · `frontend/src/hooks/useWebSocket.ts:237`
  改：sessionStore 加 `lastError`（对原生 Event 兜底成「连接错误」），在 sendMessage 置 thinking 的同一次
  set 里清空；MessageList 在 `status==="error"` 渲染红色系统气泡显示 lastError；Dashboard.startChat 的
  catch 也给可见提示。
- **P1｜消息列表无虚拟化且未 memo，流式期间每 token 全量重渲 + 强制吸底** · `frontend/src/components/chat/MessageList.tsx:36`
  长会话越用越卡、无法向上滚。改：`React.memo` 包裹 MessageBubble/MarkdownContent；自动滚动改条件式
  （记录 `isPinnedToBottom` 距底<80px 才吸底，流式用 `behavior:"auto"`，新增 user 消息才无条件到底）；
  消息量大时再上 react-virtuoso。
- **P2**：快速切换会话竞态（`sessionStore.ts:122`，await 后校验 `currentSessionId`）；前端 90s 工具超时短于
  后端合法时长（`useWebSocket.ts:9`，提到 ≥300s 或按 status 心跳重置，且迟到结果替换而非丢弃）；
  删除会话无二次确认无失败反馈（`Sidebar.tsx:102`，加 confirm + try-catch + 成功后再 navigate）。

### 6.2 飞书集成
- **P1｜Redis 不可用时所有飞书消息静默丢弃，用户无任何反馈** · `backend/api/routes/feishu_handler.py:209`
  去重 `self._seen` 在 Redis 失败时 raise，且位于 try 之外 + fire-and-forget 调度，异常被吞、HTTP 已返回
  200 飞书不重投。一次 Redis 抖动即整条飞书通道静默瘫痪。**改法**：`self._seen` 调用点降级为「失败即放行」
  （try-except 记 warning 后按未见过继续），保留 seen() 抛出契约（否则违反 `test_feishu_event.py:172` 两条
  断言）；给 `feishu.py:134` 的 create_task 加 `add_done_callback` 记录未捕获异常。
- **P1｜飞书主回调路由签名校验形同虚设（读了不存在的 Header）** · `backend/api/routes/feishu.py:86`
  `feishu.py`/`feishu_card_action.py` 读 `X-Lark-Signature-Timestamp/Signature`（不存在），真实是
  `X-Lark-Request-Timestamp/Nonce` + `X-Lark-Signature`，故 `if timestamp and signature` 恒 False、
  **签名分支永不执行**，且算法也与飞书 v2 不符。任何知道回调 URL 的人可伪造事件、点击式批准工具调用、
  触发 rerun。**改法**：删自带 `_verify_signature`，复用 `backend/common/feishu_signature.verify_signature`
  读正确三 Header + token/encrypt_key；配了 token 而签名缺失时拒绝；保留 url_verification challenge 在校验前；
  启用加密时接入 `decrypt_payload`（参照已正确的 `feishu_events.py`）。
- **P1｜多工具审批卡片：处理一个工具清掉其余按钮，其余调用挂到超时** · `backend/api/routes/feishu_card_approval.py:105`
  `_update_action_card` 用单工具状态卡替换整条多工具消息。**改法**（首选方案一）：`send_tool_approval_card`
  对 calls 逐个 `build_tool_approval_card([call])`+send，各拿独立 message_id，点击只更对应那张（按钮 value 已带
  tool_call_id，无需额外映射）。
- **P2**：卡片按钮无幂等，连点『重新执行』重复执行（`feishu_card_action.py:93`，Redis SET NX 去重）；
  未完成计划的『继续/放弃』把用户锁死切模式也解不开（`feishu_plan_resume.py:18`，direct_mode 里 pop
  `_pending_resume` 并删 checkpoint，给提示出路）；`feishu_handler.py` 510 行超限需拆分。

### 6.3 LLM Adapter 层
- **P1｜流式遇 4xx 时 `error_message` 触发 `httpx.ResponseNotRead`，真实 API 错误被吞成 STREAM_ERROR** · `backend/adapters/openai_streaming.py:91`
  未读 body 就调 `_raise_for_status` → `response.json()` 抛 ResponseNotRead 被吞 → 兜底 `response.text` 再抛。
  用户拿到误导性 "STREAM_ERROR" 而非真实的 "prompt is too long"，也堵死了上层识别上下文超限。**改法**：三处流式
  路径在 `_raise_for_status` 前 `if response.status_code >= 400: await response.aread()`（httpx 允许 stream 内
  aread，`>=400` 守卫不影响成功流）；`error_message` 兜底改 `try: return response.text except: return f"HTTP {code}"`。
  ⚠️有效回归测试须制造「真正未读取的流式 body」（起本机 http.server / ASGITransport / 自定义 AsyncByteStream），
  用 `MockTransport(content=)` 会假绿。
- **P1｜流式路径 token 用量恒为 0，日志与指标全部失真** · `backend/adapters/anthropic_stream.py:16`
  主循环默认走流式，但三个 adapter 流式解析都不采集 usage，`StreamChunk` 也无 usage 字段 →
  Redis/Prometheus token 计数全 0，也让 §2 的「用真实 prompt_tokens 校准压缩」失去数据源。**改法**：
  `StreamChunk.type` 加 `"usage"`；Anthropic 读 `message_start`(input/cache) + `message_delta`(output)，
  **按字段取末值不能求和**；OpenAI 加 `stream_options={"include_usage":True}` 但**按 provider 能力开关/降级**
  （第三方网关不认会 400）；Ollama 读 done 的 `prompt_eval_count/eval_count`；`complete_with_stream` 加 usage
  分支填 `LLMResponse.usage`。
- **P1｜Anthropic thinking 模式完全不可用** · `backend/adapters/anthropic_support.py:43`
  `thinking_enabled` 时仍无条件带 `temperature=0.7`，与 extended thinking 互斥必 400；流式又丢 signature 导致
  多轮 tool-use 再 400。**改法**：`if request.thinking:` 分支 `payload["temperature"]=1.0`（对称
  `openai_thinking.py:14`）；`budget_tokens=max(1024, min(4096, max_tokens-1))`；`anthropic_stream.py` 增
  `signature_delta` 分支贯穿 thinking-block 累加器经 provider_metadata 回传（短期兜底：`_assistant_message`
  过滤缺 signature 的 thinking block）。
- **P2**：上下文超限无专门错误码无法反馈压缩模块（`anthropic_adapter.py:181`，400 分支按关键词抛
  `CONTEXT_OVERFLOW`——与 §2 兜底联动）；流式 5xx 零重试 + 429 退避无抖动（`anthropic_adapter.py:114`）；
  OpenAI 流式 tool_call 合并用 `dict.get(k, fallback)`，provider 发 null 会清空累积（`openai_support.py:147`，
  改 `or` 保护）；每次请求新建 httpx.AsyncClient 无连接池（`openai_adapter.py:76`，改惰性共享 client + aclose）。

### 6.4 API / 配置 / 部署
- **P1｜默认 `auth_secret` 是公开仓库常量且 `.env.example` 原样下发，无启动强校验** · `backend/config/settings.py:36`
  运维照抄 `.env.example` 即让所有受保护路由能被公开的 `Bearer change-me-in-production` 访问。**改法**：
  `_validate_runtime_settings` 加「空或等于默认值即抛 `AUTH_SECRET_INSECURE` 拒绝启动」；**必须配套**在
  `tests/conftest.py` `setdefault("AUTH_SECRET","test-secret")`（否则导入期校验崩 pytest）；`.env.example`
  改占位符；`cookie_sync.py:37` 顺手改 `secrets.compare_digest`。
- **P1｜Prometheus http 指标以未匹配原始路径为 label，公网扫描致基数无限膨胀内存泄漏** · `backend/api/middleware/request_trace.py:72`
  404/未匹配路由回退用 `request.url.path` 做 label，prometheus_client 永不回收。扫描器请求随机 URL →
  label 基数无限增长 → OOM。**改法**：`_route_path` 在 `scope.get("route")` 为 None 时返回固定常量
  `"unmatched"`，只把已注册路由模板作为 label。
- **P1｜`/reports` 无鉴权且 markdown 不过滤原始 HTML，同源存储型 XSS** · `backend/api/routes/reports.py:144`
  报告由 Agent 从外部网页生成，python-markdown 默认透传 `<script>`，以 HTMLResponse 同源返回可窃取
  localStorage 的 bearer token。**改法**：给 HTMLResponse 加 CSP `default-src 'self'; script-src 'none';
  style-src 'unsafe-inline'`（零依赖、最稳）+ 可选 nh3 清洗；`/reports` 不宜无脑加 Bearer（浏览器直链不带
  header 会打断查看），宜用「输出清洗+CSP」或不可猜 URL；`/metrics` 用网络策略限内网。
- **P2**：ProviderManager 进程内内存缓存，多 gunicorn worker 配置状态分裂（`providers.py:24`——注意
  docker-compose 已设 `GUNICORN_WORKERS=1`，放开前必须先解决，否则任务队列/pubsub/会话表全分裂）；
  CORS `allow_origins=['*']`+`allow_credentials=True`（`app.py:151`，改白名单）；`config/*.toml` 全空且无代码
  加载，运维改动静默失效（实现加载器或删除并在文档标注「配置走 .env」）；SSE 客户端断开不取消 loop.run
  产生孤儿运行（`chat_completions.py:125`，try/finally cancel）。

---

## 7. 空壳模块与文档一致性（架构规范汇总）

> 本节把所有「架构规范违规」与「空占位」合并，避免刷条数。核心是**文档宣称的能力与代码不符**，
> 对招聘/交接/继续开发都有误导性。

- **s09_agent_teams / s10_team_protocol：全部 18 个文件为 0 字节空壳**，但 `docs/architecture/overview.md:25`
  与 `tasks/ARCHITECTURE.md:279` 宣称团队能力已存在，`tasks/comparison-report.md:586` 甚至把它列为相对
  DeerFlow 的**已有优势**。→ 统一口径为「(预留，未实现)」或补最小 `NotImplementedError` 接口；修订对比报告。
- **s03_todo_write / s11_autonomous_agent / s12_worktree_isolation / permissions：共 34 个 .py 全为空**。
  真实能力在别处（todo→`s01/plan_todo_tool`，权限→`s02/security_gate`）。→ 删空目录或在 `__init__.py` 写明
  占位，并在 PROJECT_OVERVIEW/ARCHITECTURE 标注真实位置。
- **内置角色定义双份并存**：`agents/builtin/*.md` 顶层 5 个为 0 字节空文件，真实定义在 `<role>/agent.md`
  目录形式，编辑顶层文件**静默无效**（`agent_definition.py:64`）。→ 删顶层空文件统一目录形式，补
  `list_roles()` 每个角色可加载的单测。
- **单文件超 200 行**（违反 CLAUDE.md）：`feishu_handler.py`(510)、`websocket.py`、`useWebSocket.ts`(271)、
  多个 s02 工具（`proxy_lifecycle.py` 等）、s07 executor 等 —— 按职责拆分到 support 模块。
- **绕过 `__init__.py` 深层导入 / core 反向依赖 api**：`websocket.py:12` 直接 import 子模块；
  `backend/api/task_queue_consumer.py` 让 core 反依赖 api 层；`storage/models.py:153` 静默吞掉知识库表
  `ImportError`（pgvector 是必需依赖，应 fail fast）。→ 收敛依赖方向，`except ImportError` 改记 error 并重抛。

---

## 8. 修复路线图（建议批次）

**批次 1 — 安全与「必坏」止血（本周）**
`P0-1` 加鉴权 · `P0-3` Bash 审批/收窄 · `P1` 飞书签名 · `P1` 默认 secret 强校验 ·
`P1` /reports CSP · `P1` Prometheus label 常量化。
（全是小改动、公网风险最高，且互相独立可并行。）

**批次 2 — 上下文/记忆正确性（1–2 周）**
`P0-2` 压缩边界修正 + sanitize 自愈 · `P1` websocket 覆盖 DB 守卫 · `P1` token CJK 加权 + 上限进 settings ·
`P1` 压缩并发锁 · `P1` 知识入库幂等(upsert)+心跳 · `P2` 记忆文件降级+原子写。
（决定「长会话能不能一直用下去」。）

**批次 3 — 长时稳定性（2–3 周）**
`_loops` LRU/TTL · abort 标志清零 · WS 清理异常安全 · sub_agent_tasks/sessions 聚合查询+定期 GC ·
scheduler 恢复后台化 · PENDING 对账 · artifact GC 容错+API 进程接线+共享 data 卷。
（决定「跑几周会不会越来越慢/OOM」。）

**批次 4 — 前端与协作可用性（2–3 周）**
Web 审批 UI · 未知事件中性化 · 断线 resync · 错误呈现 · MessageList memo+条件吸底 ·
readonly 白名单 · orchestrate 并发上限 + 失败传播 · adapter 4xx/usage/thinking 三修。

**批次 5 — 技术债与文档一致性（滚动进行）**
空壳模块清理/标注 · 超行拆分 · 依赖方向收敛 · 消息主键扩位 · run_traces/建表双轨治理 · adapter 连接池。

> 测试补齐贯穿全程：CLAUDE.md 要求每个公开接口至少一个用例，本次多条修复都点名了对应单测
> （压缩边界、鉴权、飞书降级、入库幂等、abort 清零等），建议随修复一并提交，避免回归。

---

## 附录　被证伪剔除的发现（勿据此行动）

以下 7 条经证伪 agent 用真实代码推翻或大幅降级，**不建议按原描述修复**：

1. **Bash 子进程超时可绕过致永久卡死**：行号属实但因果链被现有 `asyncio.to_thread`+上层 wait_for 覆盖，
   实际不会永久卡死整个循环。
2. **Ollama 流式 `json.loads` 无容错致整流中断**：代码事实成立，但触发前提（半截 NDJSON）在实际
   传输语义下几乎不可达。
3. **飞书大量 fire-and-forget task 被 GC 中途取消**：Python 对 create_task 有强引用直到完成，前提不成立。
4. **卡片审批 open_id 为空对任何人放行**：`_operator_allowed` 确 fail-open，但给出的具体攻击链在签名
   （一旦修好 §6.2）前提下不可达。
5. **存储层时间戳混用本地/UTC 差 8 小时**：代码事实属实但影响面被夸大，非功能性缺陷。
6. **SkillLoader 不兼容 frontmatter 致金融技能全不可用**：机制可复现但「完全不可用/用户无感知」被证伪。
7. **timeout_seconds 在定时任务路径完全不生效**：被 `scheduler.py:99` 的 `wait_for(…, 600)` 直接证伪。

---

*生成方式：13 维度并行审查 + 每条独立 Opus 4.8 证伪。完整逐条证据（含证伪 agent 的
reasoning 与 fix_feasibility）见 workflow 运行记录 `wf_efc2ea15-f04`。*

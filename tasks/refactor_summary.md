# LLM Request Refactor Summary

Date: 2026-05-17

## Commits

- `fefdee2` `refactor(llm): D1 layer request context`
- `425a793` `refactor(adapters): D2 add cache-aware payloads`
- `a4ee9c6` `refactor(compression): D3 add layered compaction`
- `110e247` `refactor(tools): D4 add history lookup`
- `8eaeb25` `refactor(skills): D5 add on-demand injection`
- `8b6ee0a` `refactor(memory): D6 add long-term memory index`
- `6c7e1f6` `refactor(tools): D7 split side-effect execution`
- `5735557` `refactor(plan): D8 share cache prefix for sub agents`

## Changed Files

- `backend/common/types/llm.py`: Added layered request zones while preserving legacy `messages`.
- `backend/common/types/tool.py`: Added conservative `side_effect=True` scheduling metadata.
- `backend/adapters/anthropic_support.py`: Moved Anthropic system prompt to top-level `system` and added ephemeral cache breakpoints.
- `backend/adapters/openai_support.py`: Uses stable system/skill/memory/summary/recent ordering for OpenAI payloads.
- `backend/adapters/message_zones.py`: Centralized adapter message-zone flattening.
- `backend/core/s01_agent_loop/agent_loop.py`: Added layered compressor, skill loader, memory index, and static Zone 2 messages.
- `backend/core/s01_agent_loop/agent_loop_run.py`: Wires layered request building, L1/L2/L3 compression, and side-effect tool scheduling.
- `backend/core/s01_agent_loop/agent_loop_support.py`: Builds cache hashes and layered LLM requests.
- `backend/core/s01_agent_loop/tool_batching.py`: Splits signed calls by side effects and restores original result order.
- `backend/core/s01_agent_loop/plan_execute_runner.py`: Carries stable system prompt, skill prompt, and step artifact directory into plan execution.
- `backend/core/s01_agent_loop/plan_execute_runner_steps.py`: Routes `agent_step` vs `script_step` and builds step loops with Zone 2 prompts.
- `backend/core/s01_agent_loop/plan_models.py`: Adds `PlanStep.type`, `tool_name`, and `tool_arguments`.
- `backend/core/s01_agent_loop/plan_prompt.py`: Documents `agent_step` and `script_step` planning schema.
- `backend/core/s01_agent_loop/plan_script_step.py`: Executes direct script/thick-tool plan steps without opening a sub loop.
- `backend/core/s01_agent_loop/plan_step_artifacts.py`: Archives full step outputs under `data/steps`.
- `backend/core/s01_agent_loop/plan_step_checkpoint.py`: Restores step checkpoints with layered prompt compatibility.
- `backend/core/s01_agent_loop/plan_step_runner.py`: Holds plan step execution helpers.
- `backend/core/s02_tools/executor.py`: Adds signed serial execution while keeping read-only batch execution concurrent.
- `backend/core/s02_tools/security_gate.py`: Allows out-of-order verification while still blocking replayed signed calls.
- `backend/core/s02_tools/builtin/read_history.py`: Adds bounded history/artifact lookup.
- `backend/core/s02_tools/builtin/load_skill.py`: Adds explicit skill loading tool.
- `backend/core/s02_tools/builtin/{file_read,file_grep,file_glob,query_specs,lingxi,x_search,youtube_search,youtube_search_ytdlp}.py`: Marks read-only/search tools as `side_effect=False`.
- `backend/core/s05_skills/models.py`: Adds skill `mode`, `trigger_keywords`, and `inject_max_chars`.
- `backend/core/s05_skills/on_demand_loader.py`: Implements inject/loop skill loading.
- `backend/core/s05_skills/skill_matcher.py`: Matches only inject-mode skills.
- `backend/core/s05_skills/runtime.py`: Moves spec prompts into Zone 2 static skill messages.
- `backend/core/s05_skills/runtime_plan.py`: Passes stable prompt plus dynamic skill prompt into plan runners.
- `backend/core/s06_context_compression/*.py`: Adds layered compression, retention template, memory index, memory models, artifact GC, and exports.
- `backend/core/system_prompt.py`: Adds P1-P6 compression retention and read-history guidance.
- `backend/config/settings.py`: Adds L2/L3 compaction thresholds.
- `backend/storage/memory_store.py`: Adds JSON-backed memory store.
- `backend/storage/__init__.py`: Lazily exposes `MemoryStore`.
- `backend/sub_worker.py`: Starts artifact GC loop.

## Tests Added

- `backend/tests/unit/test_cache_prefix_stable.py`
- `backend/tests/unit/test_adapter_layered_payload.py`
- `backend/tests/unit/test_layered_compressor_l1.py`
- `backend/tests/unit/test_layered_compressor_l2.py`
- `backend/tests/unit/test_layered_compressor_l3_p1_p2.py`
- `backend/tests/unit/test_read_history_truncation.py`
- `backend/tests/unit/test_skill_inject_mode.py`
- `backend/tests/unit/test_memory_index_topk.py`
- `backend/tests/unit/test_parallel_side_effect_split.py`
- `backend/tests/unit/test_sub_agent_cache_prefix.py`

## Verification

| Item | Result | Evidence |
| --- | --- | --- |
| F1 cache prefix | PARTIAL | Local payload/hash tests pass; no real Anthropic API call was made, so `cache_read_input_tokens` is not available. |
| F2 context stable | PARTIAL | L1/L2/L3 unit tests pass; 30-turn product-search soak not run in this environment. |
| F3 P1/P2 retention | PASS | `test_layered_compressor_l3_p1_p2.py` passes. |
| F4 read_history | PASS | `test_read_history_truncation.py` passes. |
| F5 Skill dual mode | PASS | `test_skill_inject_mode.py` passes. |
| F6 cross-session memory | PASS | `test_memory_index_topk.py` covers match/inject/store APIs. |
| F7 parallel side-effect split | PASS | `test_parallel_side_effect_split.py` passes. |
| F8 sub-agent cache sharing | PARTIAL | `test_sub_agent_cache_prefix.py` verifies dynamic prompts do not affect `cache_prefix_hash`; no real Anthropic usage sample. |
| F9 cache disabled fallback | PASS | Adapter layering tests and existing payload tests pass. |
| F10 coverage | PASS | Added 10 targeted test files; final full suite: `817 passed, 89 skipped`. |

## Test Logs

- D3 full suite: `802 passed, 89 skipped`.
- D6 full suite: `812 passed, 89 skipped`.
- D7 full suite: `814 passed, 89 skipped`.
- D8 final full suite: `817 passed, 89 skipped, 1847 warnings in 228.25s`.

## Token Savings Estimate

Real `cache_read_input_tokens` was not measured because no live Anthropic request was made. Based on the implemented payload shape, the stable prefix is now `system_prompt + tools`; when provider cache hits, expected recomputation savings per follow-up request are approximately:

`cached_prefix_tokens / total_input_tokens`.

For sub agents and plan steps with identical stable prompt/tool definitions, dynamic skill/step instructions now live in Zone 2, so they no longer invalidate the Zone 1 prefix cache. Tool-result L1 compression stores large outputs on disk and leaves roughly a brief summary plus path in context.

## Known Risks

- Ollama and any non-OpenAI/Anthropic adapters may need equivalent layered payload review.
- Real Anthropic cache-read usage still needs staging validation with provider telemetry.
- Step artifact retention is written under `data/steps`; GC currently covers `data/artifacts` and `data/sessions`.
- Memory write-back at conversation end is intentionally not wired in D6; only storage and lookup APIs are implemented.
- Existing long files outside the new helper modules remain over the 200-line project limit and should be split in a follow-up cleanup.

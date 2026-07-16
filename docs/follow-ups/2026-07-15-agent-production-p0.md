# Agent 生产化 P0 —— 跟进项（有意延后，非阻断）

日期：2026-07-15

来源：`feat/agent-production-p0`
主 spec：[docs/superpowers/specs/2026-07-15-agent-production-design.md](../superpowers/specs/2026-07-15-agent-production-design.md)
实现计划：[docs/superpowers/plans/2026-07-15-agent-production-p0.md](../superpowers/plans/2026-07-15-agent-production-p0.md)

以下项均为**有意延后**或**部署侧手工动作**，非代码缺陷。列此以便下一阶段直接消化。

## 部署/运维待办（合入后手动执行）
- [ ] 运行 Alembic 迁移创建 `agent_runs` / `agent_steps`：`alembic upgrade head`
- [ ] 确认生产 env 设置 `AGENT_TIMEOUT_S`（默认 120）、`AGENT_MAX_RECURSION_DEPTH`（默认 3）

## P1 跟进（划归下一阶段）
1. 工具并行调用（当前串行执行 LLM 请求中的多个 `tool_calls`）
2. 子 agent / agent 编排 agent（递归深度当前只设防护上限，未真正开放递归调用）
3. 人工审批中断（human-in-the-loop）
4. 动态注册工具的可执行体（`POST /tools` 当前只存 schema，注册后不可调用）
5. langgraph 模式当前与 react 共用统一循环，未来可恢复真正的状态图编排
6. run 级 `total_cost` 精确折算（当前 `end_run` 传 0，成本记在 `usage_records`；如需 run 级成本汇总可在 `record_usage` 后回填）
7. 流式 SSE 事件粒度：P0 的 `run_stream` 先落地 `run_start` + `done` 两事件（run-then-done）；spec 4.2 的逐步 `step` / `tool_call` / `tool_result` / `token` 细粒度事件在 P1 补齐（需 `run_tool_loop` 暴露异步事件生成器版本）

## 增补跟进（本次实施中新识别）
8. **run 级观测指标**：Prometheus 侧目前仅有 `/metrics` 基线，`agent_runs` 的状态分布（`completed` / `halted_quota` / `halted_timeout` / `halted_recursion` / `error`）、`latency_ms` 直方图、`total_steps` 均未导出为指标。建议在 `record_usage` 之后追加 `AGENT_RUN_STATUS_COUNTER` / `AGENT_RUN_LATENCY_HISTOGRAM`，接入 P0-M8 的观测栈。
9. **agent_runs / agent_steps 生命周期**：目前无 TTL / 归档策略，`agent_steps` 的 `input_snapshot` / `output_snapshot` 为完整 JSON，长期会膨胀。建议规划：
   - 短期：加索引 `(workspace_id, created_at)` 以支持时间窗查询与批量删除；
   - 中期：按 `retention_days`（新增配置）定期归档到冷存储或直接清理。
10. **audit_logs ↔ agent_runs 关联**：已在 P0 收尾修复中把 `audit_logs.resource_type='agent_run'` 且 `resource_id=agent_run.id`（成本/模式落 detail JSON），运营可用 `resource_id=run.id` 直接反查审计条目。仍待建的：`GET /agent-runs/{id}/audit` join 视图（复用 `QA_REVIEW` 权限），放到 P1 复审工单流下一次迭代。

## Re-review 后追加（Low，非阻断）

以下 6 项来自 whole-branch review 后的复审，均非阻断，纳入 P1 打磨。

11. **max_steps 语义变更（200 OK + 强制 final）**：`HALTED_MAX_STEPS` 现在走 200（带 final answer），而非 429。这是 spec §4.1 "用已有信息强制生成 final answer" 的原意，行为正确；但对旧客户端而言与"配额/超时→4xx"的一致性有轻微断裂，建议在 API 文档上显式区分：**QUOTA/TIMEOUT = 4xx**、**MAX_STEPS = 200 + 带 `status` 字段告知截断**。
12. **兜底 SystemMessage 稳定性**：`llm_loop.py` 撞 max_steps 时向 messages 追加 `SystemMessage("步数已达上限…")` 做无 tools 收敛。部分 provider（历史上 Ollama 少数版本）对"第二条 SystemMessage"处理不稳定，建议 P1 改为 `HumanMessage` 或改造为在原 SystemMessage 里内嵌"if step budget exhausted"指令。
13. **single_shot final 仍绑定 tools**：direct 模式的"取最终答复"这一步 `await bound.ainvoke(messages)` 仍带 tools，与 max_steps 兜底路径（用未绑定 `chat.ainvoke`）不一致。当前 LLM 通常会给文本答复（因为工具结果已在 messages 里），但在极端情况下仍可能再吐一次 tool_call。P1 统一为无 tools 收敛。
14. **`max_steps=1 + single_shot` 边界**：`check_step(db, ctx, step_index + 1)` 会用 `step_index + 1 = 1` 触发 `HALTED_MAX_STEPS`。理论上 direct 单轮场景下不会命中（因为 single_shot 分支已经跳出主循环），但如果未来把 max_steps 显式配成 1，direct 会立即熔断。建议 P1 让 direct 的 `single_shot` 忽略 `max_steps=1` 或让 `check_step` 认可 direct 模式的"这次是最后一次"。
15. **`except Exception` 面过宽**：兜底 final 里的 `except Exception:` 也会吞 `HaltSignal`（后者未来若继承 Exception 的话）。当前 `HaltSignal` 是 dataclass-based，问题不显性；P1 显式改成 `except (LLMError, TimeoutError, HTTPError, …)` 或让 HaltSignal 独立于 Exception 分支。
16. **Halt/Error 路径无审计**：`audit.log(AGENT_QUERY, …)` 只在 SUCCESS 分支落表；QUOTA/TIMEOUT/MAX_STEPS/未捕获异常都进不了 `audit_logs`。运营复盘看不到"这次 run 被 429 熔断"。建议 P1 在 `try/except HaltSignal / except Exception` 里也各写一条 audit（`detail.status` 记录终态）。

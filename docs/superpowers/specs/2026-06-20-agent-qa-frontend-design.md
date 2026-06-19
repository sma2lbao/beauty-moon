# Agent Q&A Frontend Design

## Overview

Enhance the existing Luna Corpus Q&A page so it always uses the Agent API instead of the legacy RAG Q&A streaming endpoint. The page will support all backend Agent modes, allow users to select enabled tools, and show a concise execution progress trail while the Agent works.

## Goals

- Replace the Q&A page request flow with `/api/v1/agent/stream`.
- Support `direct`, `react`, `plan`, and `langgraph` modes from the existing Q&A page.
- Fetch available tools from `/api/v1/agent/tools` and let users choose which tools are enabled for a query.
- Show user-friendly execution steps, not full tool arguments or raw tool outputs.
- Preserve the existing message-based Q&A interaction: submit, clear input, stream an assistant response, persist the completed message.

## Non-goals

- Do not keep a separate legacy RAG Q&A mode in the UI.
- Do not add an Agent management page for tool registration or debugging.
- Do not expose full tool call logs, raw parameters, or raw tool results in the normal Q&A flow.
- Do not add frontend fallback tool definitions if `/api/v1/agent/tools` fails.

## Architecture

The frontend will add Agent-specific API types and streaming helpers in `apps/luna-corpus-web/src/lib/api.ts` or a small adjacent module if the file becomes crowded.

On Q&A page load:

1. Fetch `GET /api/v1/agent/tools`.
2. Store the returned tools in page state.
3. Initialize the selected tools to all available tools unless the UI state later chooses otherwise.

On question submission:

1. Add the user message to the message list.
2. Create a streaming assistant message state.
3. Send `POST /api/v1/agent/stream` with:
   - `query`: submitted question
   - `mode`: selected Agent mode
   - `available_tools`: selected tool names
   - `stream`: `true`
4. Consume Server-Sent Events from the response body.
5. Normalize Agent events into a UI state containing answer text, execution steps, tool call summaries, completion state, and error state.
6. Persist the completed assistant message in chat history.

The Q&A page will stop calling `/api/v1/qa/stream`.

## UI Design

The Q&A page keeps its current layout and adds a lightweight Agent configuration bar between the page title and message card.

The configuration bar contains:

- Agent mode selector with `direct`, `react`, `plan`, and `langgraph` options.
- Tool multi-select populated from `/api/v1/agent/tools`.
- Loading or error feedback for tool discovery.

The default mode is `react` because it best matches an Agent flow that can reason, call tools, and produce visible steps.

During execution, the assistant message bubble shows:

- Concise execution steps.
- The streamed or final answer text.
- A loading indicator while the Agent is still running.
- An error message if the stream fails or emits an error.

Example steps:

- 开始处理
- 规划中
- 执行第 1/3 步
- 调用工具：rag_search
- 工具执行完成
- 生成最终回答

The input box behavior remains unchanged: it clears after submit and is disabled while streaming.

## Agent Event Mapping

Agent stream events will be normalized for the UI:

| Event | UI behavior |
| --- | --- |
| `start` | Add “开始处理”. |
| `phase` | Add or update a phase step such as “规划中”, “执行中”, or “总结中”. |
| `plan` | Add “已生成执行计划”. |
| `step` | Add “执行第 X/Y 步”. |
| `thought` | Show a generic “分析中” step; do not display raw thought content. |
| `tool_call` | Add “调用工具：<tool>”. |
| `tool_result` | Add “工具执行完成”. |
| `token` | Append or set answer content. Accept both string data and `{ content }` data. |
| `done` | Persist the final answer, tool call summaries, and steps. |
| `error` | Mark the assistant response as failed while keeping the user message visible. |

The frontend will tolerate differences between modes. For example, `done` may include only `answer`, or may include `answer` and `tool_calls`. `token` may be a string or an object with `content`.

## Data Model

The Q&A message model will evolve from RAG-specific answer data to Agent-specific assistant data.

An assistant Agent message stores:

- `answer`: final or streamed answer text
- `mode`: selected Agent mode
- `steps`: user-facing execution steps
- `toolCalls`: summarized tool call names and success status when available
- `error`: optional failure message

Source cards from the legacy RAG response are not part of the Agent UI unless the Agent answer text itself includes citations.

## Error Handling

Tool discovery errors show a visible message in the configuration bar. Because the design does not use fallback tool definitions, the user cannot submit Agent queries until tools are loaded successfully.

Stream failures show an error in the current assistant bubble. The submitted user message remains in history, and the input is re-enabled after the stream ends.

Invalid or unknown stream events are ignored unless they carry an error payload.

## Testing

Testing should cover:

- Agent API stream parsing for string and object `token` payloads.
- `done` payloads with and without `tool_calls`.
- Tool discovery success and failure states.
- Mode selection and tool multi-select request parameters.
- Rendering of concise execution steps.
- Error display when the stream fails.
- Regression of existing input behavior: disabled during streaming, clears on submit, and preserves submitted user messages.

## Acceptance Criteria

- Q&A submissions use `/api/v1/agent/stream` and no longer use `/api/v1/qa/stream`.
- Users can select any backend Agent mode before submitting a question.
- Users can choose enabled tools from the backend-provided tool list.
- The assistant bubble shows concise execution progress while streaming.
- Final responses are persisted in the message list.
- Tool discovery and stream errors are visible and recoverable.

# 工具调用与任务规划系统设计

**日期**: 2026-06-17
**状态**: 已批准

---

## 1. 概述

为 luna-corpus RAG 系统添加 Agent 能力，支持工具调用和多种任务规划模式，使 AI 能够执行复杂的多步骤任务。

**设计目标**:
- 统一的工具注册与执行框架
- 支持四种执行模式：Direct、ReAct、Plan-Execute、LangGraph
- 与现有 RAG 系统无缝集成
- 灵活的工具扩展机制

---

## 2. 架构概览

```
┌─────────────────────────────────────────────────────────────┐
│                      User Query                              │
└─────────────────┬───────────────────────────────────────────┘
                  ▼
┌─────────────────────────────────────────────────────────────┐
│                    Tool Executor 统一入口                     │
│  ┌─────────┐ ┌─────────┐ ┌─────────────────┐ ┌────────────┐ │
│  │ Direct  │ │  ReAct  │ │ Plan-Then-Exec  │ │ LangGraph  │ │
│  │ Agent   │ │  Agent  │ │     Agent       │ │  Workflow  │ │
│  └────┬────┘ └────┬────┘ └───────┬─────────┘ └─────┬──────┘ │
│       │           │               │                 │        │
└───────┼───────────┼───────────────┼─────────────────┼────────┘
        │           │               │                 │
        ▼           ▼               ▼                 ▼
┌─────────────────────────────────────────────────────────────┐
│                    Tool Registry (Schema 驱动)               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐   │
│  │ 搜索工具  │ │ 代码执行  │ │ 内部 API  │ │ RAG 检索工具 │   │
│  └──────────┘ └──────────┘ └──────────┘ └──────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 工具定义层（混合模式）

### 3.1 装饰器模式（便捷层）

适用于内部 Python 函数：

```python
from luna_corpus.agent import tool

@tool(
    name="calculator",
    description="执行数学计算，支持加减乘除和函数",
    parameters_schema={
        "type": "object",
        "properties": {
            "expression": {
                "type": "string",
                "description": "数学表达式，如 '2 + 3 * 4'"
            }
        },
        "required": ["expression"]
    }
)
def calculate(expression: str) -> str:
    """计算数学表达式的结果"""
    try:
        result = eval(expression, {"__builtins__": {}}, {})
        return str(result)
    except Exception as e:
        return f"计算错误: {str(e)}"
```

### 3.2 Schema 模式（灵活层）

适用于外部服务、API、动态工具：

```python
from luna_corpus.agent import Tool, ToolExecutor

web_search_tool = Tool(
    name="web_search",
    description="搜索网络获取实时信息",
    parameters_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "搜索关键词"},
            "limit": {"type": "integer", "default": 5}
        },
        "required": ["query"]
    },
    executor=async def(query: str, limit: int = 5) -> str:
        # 调用外部搜索 API
        results = await external_search(query, limit)
        return format_search_results(results)
)
```

### 3.3 RAG 检索工具封装

```python
@tool(
    name="rag_search",
    description="从知识库检索相关文档内容",
    parameters_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "检索查询"},
            "top_k": {"type": "integer", "default": 5}
        },
        "required": ["query"]
    }
)
def rag_search(query: str, top_k: int = 5) -> str:
    """封装现有 RAG 检索能力"""
    chunks = vectorstore.similarity_search(query, k=top_k)
    return "\n\n".join([
        f"[文档 {i+1}] 相似度: {c.score:.3f}\n{c.content}"
        for i, c in enumerate(chunks)
    ])
```

---

## 4. 四种执行模式

### 4.1 Mode A: Direct Agent（直接执行）

**特点**: 简单任务，一次 LLM 调用

```
用户: "北京今天多少度？"
→ LLM 直接选择工具: web_search(weather=北京)
→ 返回结果
```

**实现要点**:
- 单次 LLM 调用
- 工具选择 + 执行 + 返回
- 适用于明确单一任务

**适用场景**:
- 简单查询
- 明确的任务执行
- 响应速度优先

### 4.2 Mode B: ReAct Agent（推理循环）

**特点**: Think → Act → Observe 循环

```
用户: "如果北京下雨，推荐什么室内活动？"

→ Thought: 需要先查北京天气
→ Action: web_search(weather=北京)
→ Observation: "晴天，25度"
→ Thought: 天气晴朗，不需要推荐室内活动
→ Response: "今天北京晴天，适合户外活动"
```

**实现要点**:
- 多轮 LLM 调用
- 维护对话历史和观察结果
- 循环终止条件：无更多行动 / 达到最大轮数 / 任务完成

**适用场景**:
- 需要推理的步骤
- 条件判断任务
- 探索性查询

### 4.3 Mode C: Plan-then-Execute（计划优先）

**特点**: 先生成计划，再执行

```
用户: "帮我分析这家公司并生成报告"

→ Plan Generation:
  [
    Step 1: search_company(name)     # 获取基本信息
    Step 2: search_news(name)        # 获取新闻
    Step 3: search_financial(name)   # 获取财务数据
    Step 4: generate_report([1,2,3]) # 生成报告
  ]

→ Execute:
  执行每一步，收集结果
  最终生成报告
```

**实现要点**:
- 两阶段 LLM 调用：计划 + 执行
- 计划可验证、可调整
- 支持并行执行的步骤优化

**适用场景**:
- 复杂多步骤任务
- 需要明确执行计划
- 任务可分解

### 4.4 Mode D: LangGraph（状态机）

**特点**: 可视化工作流，支持分支、回滚

```
                    ┌─────────────┐
                    │   START     │
                    └──────┬──────┘
                           ▼
              ┌────────────────────────┐
              │  classification_node   │
              │  (判断任务类型)          │
              └───────────┬────────────┘
                    ┌─────┴─────┐
                    ▼           ▼
           ┌───────────┐  ┌────────────┐
           │   simple  │  │   complex  │
           │  _agent   │  │  _agent    │
           │ (Direct)  │  │ (ReAct)    │
           └─────┬─────┘  └──────┬─────┘
                 │               │
                 └───────┬───────┘
                         ▼
                ┌─────────────────┐
                │  final_response │
                │  (结果汇总)      │
                └─────────────────┘
```

**实现要点**:
- LangGraph StateGraph 定义工作流
- 支持条件分支
- 可添加检查点（checkpoint）用于回滚
- 支持并行节点

**适用场景**:
- 复杂业务流程
- 需要人工审批
- 多 Agent 协作

---

## 5. 核心组件

### 5.1 ToolRegistry（工具注册表）

```python
class ToolRegistry:
    """统一工具注册表"""

    def register(self, tool: Tool) -> None:
        """注册工具"""

    def get(self, name: str) -> Tool:
        """获取工具"""

    def list_all(self) -> list[Tool]:
        """列出所有工具"""

    def get_schemas(self) -> list[dict]:
        """获取所有工具的 Schema（供 LLM 使用）"""
```

### 5.2 AgentMode 枚举

```python
from enum import Enum

class AgentMode(Enum):
    DIRECT = "direct"           # 直接执行
    REACT = "react"            # 推理循环
    PLAN_EXECUTE = "plan"      # 计划优先
    LANGGRAPH = "langgraph"    # 状态机
```

### 5.3 AgentFactory（工厂模式）

```python
class AgentFactory:
    """Agent 工厂，根据模式创建对应的 Agent"""

    @staticmethod
    def create(mode: AgentMode, tools: list[Tool], llm: LLM) -> Agent:
        modes = {
            AgentMode.DIRECT: DirectAgent,
            AgentMode.REACT: ReActAgent,
            AgentMode.PLAN_EXECUTE: PlanExecuteAgent,
            AgentMode.LANGGRAPH: LangGraphAgent,
        }
        return modes[mode](tools=tools, llm=llm)
```

---

## 6. API 设计

### 6.1 统一查询接口

```
POST /api/v1/agent/query
```

**Request Body**:
```json
{
    "query": "用户问题",
    "mode": "direct | react | plan | langgraph",
    "available_tools": ["web_search", "calculator", "rag_search"],
    "stream": true
}
```

**Response (非流式)**:
```json
{
    "answer": "最终回答",
    "tool_calls": [
        {"tool": "web_search", "args": {"query": "天气"}, "result": "..."}
    ],
    "mode": "react",
    "steps": 3,
    "latency_ms": 1234
}
```

**Response (流式 - SSE)**:
```
event: tool_call
data: {"tool": "web_search", "args": {"query": "天气"}}

event: tool_result
data: {"tool": "web_search", "result": "晴天，25度"}

event: token
data: {"content": "今天"}

event: done
data: {"answer": "今天天气晴朗...", "steps": 3}
```

### 6.2 工具管理接口

```
GET    /api/v1/agent/tools          # 列出所有工具
POST   /api/v1/agent/tools           # 注册新工具
DELETE /api/v1/agent/tools/{name}    # 删除工具
```

---

## 7. 内置工具集

### 7.1 核心工具

| 工具名 | 描述 | 类型 |
|--------|------|------|
| `rag_search` | 知识库检索 | 内部 |
| `calculator` | 数学计算 | 内部 |
| `current_time` | 获取当前时间 | 内部 |

### 7.2 扩展工具（按需启用）

| 工具名 | 描述 | 依赖 |
|--------|------|------|
| `web_search` | 网络搜索 | 搜索 API |
| `code_executor` | 代码执行 | 代码沙箱 |
| `send_email` | 发送邮件 | SMTP/API |
| `database_query` | 数据库查询 | DB 连接 |

---

## 8. 与现有系统集成

### 8.1 复用现有 LLM 服务

```python
# 复用现有的 LLM 服务
from luna_corpus.services.llm import LLMService

class AgentLLMWrapper(LLMService):
    """Agent 专用的 LLM 封装"""

    async def generate(self, prompt: str) -> str:
        # 复用现有 generate_stream 或 generate
        pass

    async def generate_with_tools(self, prompt: str, tools: list[dict]) -> str:
        # 支持工具调用的生成
        pass
```

### 8.2 复用现有向量存储

```python
# RAG 搜索工具直接使用现有的 vectorstore
from luna_corpus.db.vectorstore import VectorStore

class RAGSearchTool:
    def __init__(self, vectorstore: VectorStore):
        self.vectorstore = vectorstore
```

---

## 9. 配置项

```env
# Agent 配置
AGENT_DEFAULT_MODE=direct
AGENT_MAX_STEPS=10
AGENT_REACT_MAX_ITERATIONS=5
AGENT_PLAN_MAX_STEPS=10

# 工具配置
AGENT_ENABLE_WEB_SEARCH=false
AGENT_ENABLE_CODE_EXEC=false
AGENT_CODE_TIMEOUT_SECONDS=30

# 内置 RAG 工具
RAG_SEARCH_TOP_K=5
```

---

## 10. 目录结构

```
luna-corpus/
├── app/
│   ├── api/
│   │   └── routes.py              # 新增 /agent 路由
│   └── main.py
├── luna_corpus/
│   ├── agent/                     # 新增 Agent 模块
│   │   ├── __init__.py
│   │   ├── base.py                # Agent 基类
│   │   ├── registry.py            # ToolRegistry
│   │   ├── tool.py                # Tool 定义
│   │   ├── modes/
│   │   │   ├── __init__.py
│   │   │   ├── direct.py          # Direct Agent
│   │   │   ├── react.py           # ReAct Agent
│   │   │   ├── plan_execute.py    # Plan-then-Execute
│   │   │   └── langgraph.py       # LangGraph Workflow
│   │   └── tools/                 # 内置工具
│   │       ├── __init__.py
│   │       ├── rag_search.py
│   │       ├── calculator.py
│   │       └── time_tool.py
│   ├── core/
│   │   └── config.py              # 新增 Agent 配置
│   ├── graph/                     # 现有 LangGraph
│   └── services/
│       └── llm.py                 # 扩展工具调用支持
├── tests/
│   └── agent/                     # 新增测试
│       ├── test_registry.py
│       ├── test_direct.py
│       ├── test_react.py
│       ├── test_plan_execute.py
│       └── test_langgraph.py
```

---

## 11. 实现优先级

| 阶段 | 内容 | 工作量 |
|------|------|--------|
| **Phase 1** | Tool 基础框架 + Registry + Direct Agent | 中 |
| **Phase 2** | ReAct Agent + RAG 工具封装 | 中 |
| **Phase 3** | Plan-Execute Agent | 小 |
| **Phase 4** | LangGraph Workflow | 中 |
| **Phase 5** | 扩展工具 + API 完善 | 中 |

---

## 12. 验收标准

- [ ] ToolRegistry 支持注册/获取/列出工具
- [ ] 四种 Agent 模式可切换执行
- [ ] RAG 检索作为工具正常工作
- [ ] API 支持流式和非流式响应
- [ ] 单元测试覆盖核心组件
- [ ] 与现有系统无缝集成

## 📋 系统架构

系统由三个专门的 Agent 组成，采用流水线架构协同工作。
基于 **autogen_core** 和 **autogen_ext** 实现，遵循 AutoGen 最佳实践。

```
输入代码片段
    ↓
┌─────────────────────────────┐
│ Agent 1: 语义清晰度判定     │
│ SemanticClarityAgent        │
│ - 继承 RoutedAgent          │
│ - 评估命名质量              │
│ - 评估意图明确性            │
│ - 评估可理解性              │
└─────────────────────────────┘
    ↓
┌─────────────────────────────┐
│ Agent 2: 语法逻辑判定       │
│ SyntaxLogicAgent            │
│ - 继承 RoutedAgent          │
│ - 评估代码结构              │
│ - 评估控制流简单性          │
│ - 评估逻辑直接性            │
└─────────────────────────────┘
    ↓
┌─────────────────────────────┐
│ Agent 3: 综合判定           │
│ IdiomJudgeAgent             │
│ - 继承 RoutedAgent          │
│ - 综合前两个 Agent 的结果   │
│ - 判定是否为代码习语        │
│ - 给出置信度和特征          │
└─────────────────────────────┘
    ↓
输出判定结果
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install autogen-core autogen-ext
```

### 2. 配置环境变量

```bash
export OPENAI_API_KEY="your-api-key"
export OPENAI_BASE_URL="your-base-url"  # 可选
```

### 3. 单独测试每个 Agent

#### 测试语义清晰度 Agent
```bash
python -m src.agent.semantic_clarity_agent
```

#### 测试语法逻辑 Agent
```bash
python -m src.agent.syntax_logic_agent
```

#### 测试综合判定 Agent
```bash
python -m src.agent.idiom_judge_agent
```

### 4. 运行完整的多 Agent 系统

```bash
python -m src.agent.test_multi_agent
```

## 📦 文件说明

### 核心 Agent 文件

| 文件 | 说明 | 主要功能 |
|------|------|---------|
| `semantic_clarity_agent.py` | 语义清晰度判定 Agent | 评估代码的命名、意图和可理解性 |
| `syntax_logic_agent.py` | 语法逻辑判定 Agent | 评估代码的结构、控制流和逻辑 |
| `idiom_judge_agent.py` | 综合判定 Agent | 综合前两个结果判定是否为代码习语 |

### 辅助文件

| 文件 | 说明 |
|------|------|
| `test_multi_agent.py` | 多 Agent 集成测试和使用示例 |
| `__init__.py` | 模块导出 |
| `README.md` | 本文档 |

## 💻 使用示例

### 使用流水线进行判定

```python
import asyncio
from src.agent.test_multi_agent import CodeIdiomPipeline

async def main():
    # 创建流水线
    pipeline = CodeIdiomPipeline(model="gpt-4o-mini")
    
    try:
        # 评估代码片段
        code = """
def calculate_average(numbers):
    if not numbers:
        return 0
    return sum(numbers) / len(numbers)
"""
        
        result = await pipeline.evaluate(code)
        pipeline.print_result(result)
    
    finally:
        await pipeline.shutdown()

asyncio.run(main())
```

### 单独使用某个 Agent

```python
import asyncio
import os
from autogen_core import SingleThreadedAgentRuntime
from autogen_ext.models.openai import OpenAIChatCompletionClient
from src.agent import SemanticClarityAgent, SemanticClarityRequest

async def main():
    # 创建运行时
    runtime = SingleThreadedAgentRuntime()
    
    # 创建模型客户端
    model_client = OpenAIChatCompletionClient(
        model="gpt-4o-mini",
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL")
    )
    
    # 注册 Agent
    await runtime.register(
        "semantic_agent",
        lambda: SemanticClarityAgent(model_client)
    )
    
    # 启动运行时
    runtime.start()
    
    try:
        # 发送请求
        code = "def f(x): return x * 2"
        result = await runtime.send_message(
            SemanticClarityRequest(code_snippet=code),
            recipient="semantic_agent"
        )
        
        print(f"是否清晰: {result.is_clear}")
        print(f"评分: {result.score}")
        print(f"理由: {result.reason}")
    
    finally:
        await runtime.stop()

asyncio.run(main())
```

## 📊 输出格式

### 语义清晰度评估结果
```python
@dataclass
class SemanticClarityResult:
    is_clear: bool          # 是否清晰 (score >= 70)
    score: float            # 评分 (0-100)
    reason: str             # 理由
    suggestions: List[str]  # 改进建议
```

### 语法逻辑评估结果
```python
@dataclass
class SyntaxLogicResult:
    is_clear: bool       # 是否清晰 (score >= 70)
    score: float         # 评分 (0-100)
    reason: str          # 理由
    issues: List[str]    # 发现的问题
```

### 综合判定结果
```python
@dataclass
class IdiomJudgeResult:
    is_idiom: bool                # 是否为代码习语
    confidence: float             # 置信度 (0-100)
    reason: str                   # 判定理由
    characteristics: List[str]    # 识别出的习语特征
```

## 🏷️ LLM 响应格式约定

所有 Agent 与 LLM 的交互都遵循统一的标签格式约定：

### 标签格式

1. **代码片段标签**: `[Code Idiom] ... [/Code Idiom]`
   - 用于包裹代码片段
   - 确保代码的完整性和可解析性

2. **JSON 响应标签**: `[JSON] ... [/JSON]`
   - 用于包裹 JSON 格式的评估结果
   - 便于从 LLM 响应中精确提取结构化数据

### LLM 响应示例

```
Here is my evaluation:

[Code Idiom]
def calculate_average(numbers):
    if not numbers:
        return 0
    return sum(numbers) / len(numbers)
[/Code Idiom]

This code snippet demonstrates clear semantics and logic.

[JSON]
{
    "is_clear": true,
    "score": 90,
    "reason": "Clear function naming and intent",
    "suggestions": ["Consider adding type hints"]
}
[/JSON]
```

### 解析工具

系统使用 `src/utils/response_parser.py` 中的 `extract_tag_content()` 函数统一解析标签内容：

```python
from src.utils.response_parser import extract_tag_content

# 提取 JSON 内容
json_content = extract_tag_content(response, "JSON")

# 提取代码片段
code = extract_tag_content(response, "Code Idiom")
```

## 🔧 技术实现

### AutoGen 最佳实践

本系统严格遵循 AutoGen 的最佳实践：

1. **继承 RoutedAgent**: 所有 Agent 继承自 `autogen_core.RoutedAgent`
2. **使用 message_handler**: 使用 `@message_handler` 装饰器处理消息
3. **SingleThreadedAgentRuntime**: 使用单线程运行时管理 Agent 通信
4. **OpenAIChatCompletionClient**: 使用 `autogen_ext` 的模型客户端
5. **异步设计**: 全部采用异步 API
6. **结构化消息**: 使用 dataclass 定义请求和响应

### 核心组件

```python
# 从 autogen_core 导入
from autogen_core import (
    RoutedAgent,              # Agent 基类
    message_handler,          # 消息处理装饰器
    MessageContext,           # 消息上下文
    SingleThreadedAgentRuntime # 单线程运行时
)
from autogen_core.models import (
    SystemMessage,            # 系统消息
    UserMessage,             # 用户消息
    LLMMessage               # LLM 消息基类
)

# 从 autogen_ext 导入
from autogen_ext.models.openai import (
    OpenAIChatCompletionClient  # OpenAI 客户端
)
```

### 设计原则

1. **单一职责**: 每个 Agent 专注于一个评估维度
2. **流水线架构**: Agent 按顺序执行，前面的结果传递给后面
3. **结构化输出**: 使用 JSON 格式确保结果可解析
4. **可扩展性**: 易于添加新的评估维度

### Agent 通信流程

```python
# 1. 创建运行时
runtime = SingleThreadedAgentRuntime()

# 2. 注册 Agent
await runtime.register("agent_name", lambda: AgentClass(model_client))

# 3. 启动运行时
runtime.start()

# 4. 发送消息
result = await runtime.send_message(
    RequestMessage(...),
    recipient="agent_name"
)

# 5. 停止运行时
await runtime.stop()
```

## 🎯 判定标准

### 代码习语的特征

1. **语义清晰** (score >= 70)
   - 命名有意义
   - 意图明确
   - 易于理解

2. **逻辑简洁** (score >= 70)
   - 结构清晰
   - 控制流简单
   - 逻辑直接

3. **通用模式**
   - 可复用
   - 符合最佳实践
   - 被广泛认可

### 判定逻辑

- 两个维度都 >= 70 分：**很可能是代码习语**
- 一个 >= 70，另一个 >= 50：**可能是代码习语**
- 其他情况：**不太可能是代码习语**

## 🐛 常见问题

### Q: 为什么使用 autogen_core 而不是 autogen_agentchat？
A: `autogen_core` 是 AutoGen 的核心包，提供了更底层和灵活的 Agent 实现。`autogen_agentchat` 是更高级的封装，适合对话场景。对于我们的流水线判定系统，`autogen_core` 更合适。

### Q: 为什么不使用 src/llm？
A: AutoGen 自带了完善的模型客户端（`OpenAIChatCompletionClient`），功能完整且经过充分测试，直接使用可以减少依赖和潜在问题。

### Q: 如何添加新的评估维度？
A: 创建一个新的 Agent 类继承 `RoutedAgent`，定义请求和结果的 dataclass，然后在流水线中注册和调用即可。

### Q: 支持批量评估吗？
A: 可以通过循环调用 `pipeline.evaluate()` 实现批量评估，或者修改 Agent 支持批量请求。

## 📝 TODO

- [ ] 添加更多测试用例
- [ ] 支持批量评估优化
- [ ] 添加评估结果缓存
- [ ] 集成到主流水线
- [ ] 添加更多评估维度

## 📄 许可证

本项目遵循主项目的许可证。

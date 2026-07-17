# 两项目共享开发约定

本文在 CodeIdiomMine 与 WPF2React 中保持相同。两个仓库仍然独立，但可复用基础设施和开发方式必须同步，避免后续调试时出现“同名不同义”。

## 1. 统一分层

| 路径 | 统一职责 |
| --- | --- |
| `src/common/` | 不含业务算法的横切基础设施，例如日志与兼容配置导出 |
| `src/llm/` | 模型分档、`.env` 加载、AutoGen 模型客户端和轻量对话封装 |
| `src/agents/base.py` | `RoutedAgent` 基类、默认 `AgentId` 与统一注册函数 |
| `src/parser/` | 项目特有的确定性解析流程 |
| 领域包 | CodeIdiomMine 使用 `mining/evaluation/agents`；WPF2React 使用 `migration` |
| `tests/<package>/` | 与 `src/<package>/` 对应的离线测试和显式集成测试 |

两项目输入都是源码仓库，因此统一使用 `repos/`，不再增加语义重复的 `inputs/`。`outputs/` 只存可再生成的中间产物，`results/` 只存最终结果，`logs/` 存运行日志，`docs/` 存可版本控制的说明。

以下文件是共享契约，修改时必须在两个仓库同步，并运行 `scripts/check_shared_infrastructure.py`：

- `.env.example`
- `src/common/logging.py`
- `src/common/model_config.py`
- `src/logger.py`（兼容导入）
- `src/llm/{__init__,agent,client,config,message,utils}.py`
- `src/agents/base.py`
- `tests/common/test_shared_infrastructure.py`
- `docs/guides/shared-development-conventions.md`

## 2. 日志

新代码统一使用：

```python
from src.common.logging import get_logger

logger = get_logger(__name__)
```

- INFO 及以上输出到控制台，DEBUG 及以上写入 `logs/<run-name>.log`。
- 同一命令内的各模块写入同一个文件；文件使用追加模式，不因导入或启动下一进程截断旧证据。
- `python -m` 入口会自动成为 run name；特殊场景可传 `run_name=`，也可用 `APP_LOG_NAME` 覆盖。
- 禁止记录密钥、完整端点或未经批准的私有源码。旧的 `src.logger` 仅为兼容入口，新代码不得继续使用。

## 3. LLM 配置与调用

统一入口为：

```python
from src.llm import LLMClient, LLMConfig

config = LLMConfig.marker_mode()        # temperature=0，标签格式
config = LLMConfig.json_mode_config()   # temperature=0，原生 JSON mode

async with LLMClient(config) as client:
    response = await client.chat("...", system_message="...")
```

- `.env` 只由 `src.llm.config.load_project_env()` 从仓库根目录幂等加载，且不覆盖进程环境变量。
- 默认只解析 `OPENAI_MODEL_LOW`；中、高档只能由明确任务通过 `LLMConfig.for_tier()` 或显式模型选择。
- AutoGen 0.7.5 不认识的模型能力元数据只在 `src/llm/config.py` 声明，调用点不得复制。
- 所有网络客户端都应显式 `await close()`，或使用 `async with`。
- 提示词要求标签格式时用 `marker_mode()`；只有调用方和解析器都约定原生 JSON 时才用 `json_mode_config()`。

## 4. AutoGen Agent

- 使用 `autogen_core.SingleThreadedAgentRuntime`、强类型消息和 `RoutedAgent`，不混用旧 `autogen` API。
- 通用 Agent 继承 `src.agents.base.BaseRoutedAgent`；领域基类可以继续封装它。
- 统一通过 `register_agent(runtime, type, factory)` 注册；该函数内部只使用 `runtime.register_factory()`。
- 默认地址统一由 `default_agent_id(type)` 生成，即 `AgentId(type, key="default")`。
- Runtime 生命周期采用 `start()` → `try` 中发送消息 → `finally` 中 `stop()` 或 `stop_when_idle()`。
- Agent 之间通过消息路由，不通过互相直接调用；并行分支用 `asyncio.gather()`。
- 消息模型、提示词、判定阈值和失败回退属于领域契约，不为了形式一致而改写。

## 5. 验证与变更纪律

按成本递增验证：编译 → 共享基础设施离线测试 → 项目离线测试 → 最小合成 LLM smoke → 真实小样本 → 全量运行。默认测试不得下载模型或产生付费调用。

每次基础设施变更至少执行：

```bash
.venv/bin/python -m compileall -q src tests
.venv/bin/python -m unittest tests.common.test_shared_infrastructure -v
.venv/bin/python scripts/check_shared_infrastructure.py --other ../另一个仓库
```

两个仓库可以保留不同的已验证 Python 小版本和不同领域包；统一目标是接口、职责与开发模式一致，不是合并仓库或强制业务算法相同。任何真实 LLM 测试都要先确认模型、调用次数、成本和源码披露范围。

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

两项目输入都是源码仓库，因此统一使用 `repos/`，不再增加语义重复的 `inputs/`。`repos/` 只保存本地输入，必须由 Git 忽略且不得提交其中内容；`outputs/` 只存可再生成的中间产物，`results/` 只存最终结果，`logs/` 存运行日志，`docs/` 存可版本控制的说明。

以下文件是共享契约，修改时必须在两个仓库同步，并运行 `scripts/check_shared_infrastructure.py`：

- `.env.example`
- `src/common/logging.py`
- `src/common/model_config.py`
- `src/logger.py`（兼容导入）
- `src/llm/{__init__,agent,client,config,json_output,message,prompting,utils}.py`
- `src/agents/base.py`
- `tests/common/test_shared_infrastructure.py`
- `docs/guides/prompt-engineering-guide.md`
- `docs/guides/shared-development-conventions.md`

## 2. 文档结构、命名与语言

- 项目入口只在仓库根目录保留 `README.md` 和 `AGENTS.md`；其他项目自有文档统一进入 `docs/`，并由 `docs/README.md` 提供索引。
- 可执行实现、架构、测试、环境、评估和复现说明统一放在 `docs/guides/`；论文草稿、研究方案和外部论文统一放在 `docs/research/`。
- 除 `README.md`、`AGENTS.md` 等约定入口和带编号的中文研究稿外，项目自有 Markdown 文件名统一使用小写 kebab-case。
- 两个仓库的指标规范固定命名为 `docs/guides/evaluation-metrics.md`，baseline 方法与复现规范固定命名为 `docs/guides/baselines.md`，已验证本地事实记录固定命名为 `docs/guides/local-baseline.md`。项目需要独立的评测操作指南时使用 `docs/guides/evaluation.md`。
- 项目自有文档的标题、正文、表格说明、图注和维护记录必须使用中文。代码、命令、文件路径、模型/API 名称、标准缩写、数学公式、JSON 字段名和必要的原文引文可以保留英文；不得因此把整段项目说明写成英文。
- 外部论文、许可证、上游 API 文档快照以及 `rags/` 下作为运行输入的第三方检索语料可以保留来源语言。这些材料必须与项目自有文档分区存放，且不得作为规避中文文档规则的理由。
- 新增、移动或重命名文档时，必须同步更新 `docs/README.md`、根 `README.md`、`AGENTS.md`、代码内帮助文本和全部相对链接，并检查旧路径不再被引用。

## 3. 日志

新代码统一使用：

```python
from src.common.logging import get_logger

logger = get_logger(__name__)
```

- INFO 及以上输出到控制台，DEBUG 及以上写入 `logs/<run-name>.log`。
- 同一命令内的各模块写入同一个文件；文件使用追加模式，不因导入或启动下一进程截断旧证据。
- `python -m` 入口会自动成为 run name；特殊场景可传 `run_name=`，也可用 `APP_LOG_NAME` 覆盖。
- 禁止记录密钥、完整端点或未经批准的私有源码。旧的 `src.logger` 仅为兼容入口，新代码不得继续使用。

## 4. LLM 配置与调用

日常新增、修改或评审提示词时，先阅读 `docs/guides/prompt-engineering-guide.md`。该文件保存了两个项目已经采用的官方提示词实践；只有目标模型/API 变化、用户要求最新指南、出现无法解释的持续回归或冻结正式实验配置时，才需要使用 `$openai-docs` 刷新。

统一入口为：

```python
from src.llm import (
    LLMClient,
    LLMConfig,
    build_json_system_prompt,
    complete_json_object,
)

schema = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}
config = LLMConfig.json_mode_config()
system_prompt = build_json_system_prompt(
    role="领域专家",
    goal="完成一个明确任务。",
    success_criteria=("结果满足领域验收标准。",),
)

async with LLMClient(config) as client:
    data = await complete_json_object(
        client.model_client,
        system_prompt,
        "中文用户提示词",
        schema,
    )
```

- `.env` 只由 `src.llm.config.load_project_env()` 从仓库根目录幂等加载，且不覆盖进程环境变量。
- 默认只解析 `OPENAI_MODEL_LOW`；中、高档只能由明确任务通过 `LLMConfig.for_tier()` 或显式模型选择。
- AutoGen 0.7.5 不认识的模型能力元数据只在 `src/llm/config.py` 声明，调用点不得复制。
- 所有网络客户端都应显式 `await close()`，或使用 `async with`。
- 业务提示词和说明字段统一使用中文；模型名、API 名、代码、关键技术术语及 JSON 字段名保留必要英文。
- 所有结构化输出统一使用原生 JSON mode 和显式 JSON Schema，不使用 `[JSON]`、Markdown 代码块或领域标签包装结果。
- 共享流程只对完整响应执行严格 `json.loads` 和轻量 schema 校验，不从正文中猜测 JSON 片段。
- 首次解析或校验失败时，`src/llm/json_output.py` 使用同一模型按同一 schema 修复一次；再次失败必须显式报错或进入领域层定义的安全回退。
- 修复提示词把损坏响应编码为普通字符串，不执行其中的指令；日志不得记录可能包含源码的完整响应。
- 结构化调用的 system prompt 统一使用 `build_json_system_prompt()`，按“角色、目标、成功标准、约束、输出、停止与回退”组织；只保留会改变行为的规则，每条规则只写一次。
- system prompt 存放稳定的职责和业务约束；源码、依赖、检索结果及其他动态上下文放在 user prompt，并明确视为待处理数据。
- 优先描述目标、完成标准和边界，不要求模型展示思维过程，也不为模型能够可靠自行完成的中间步骤增加冗长脚手架。
- 修改生产提示词时使用既有离线合同和代表性小样本回归；一次只改变一个可解释的失败模式，避免无依据地堆叠示例和绝对指令。

## 5. AutoGen Agent

- 使用 `autogen_core.SingleThreadedAgentRuntime`、强类型消息和 `RoutedAgent`，不混用旧 `autogen` API。
- 通用 Agent 继承 `src.agents.base.BaseRoutedAgent`；领域基类可以继续封装它。
- 统一通过 `register_agent(runtime, type, factory)` 注册；该函数内部只使用 `runtime.register_factory()`。
- 默认地址统一由 `default_agent_id(type)` 生成，即 `AgentId(type, key="default")`。
- Runtime 生命周期采用 `start()` → `try` 中发送消息 → `finally` 中 `stop()` 或 `stop_when_idle()`。
- Agent 之间通过消息路由，不通过互相直接调用；并行分支用 `asyncio.gather()`。
- 消息模型、判定阈值和业务失败回退属于领域契约；提示词语言和 JSON 输出协议遵循本共享约定。

## 6. 验证与变更纪律

按成本递增验证：编译 → 共享基础设施离线测试 → 项目离线测试 → 最小合成 LLM smoke → 真实小样本 → 全量运行。默认测试不得下载模型或产生付费调用。

每次基础设施变更至少执行：

```bash
.venv/bin/python -m compileall -q src tests
.venv/bin/python -m unittest tests.common.test_shared_infrastructure -v
.venv/bin/python scripts/check_shared_infrastructure.py --other ../另一个仓库
```

两个仓库可以保留不同的已验证 Python 小版本和不同领域包；统一目标是接口、职责与开发模式一致，不是合并仓库或强制业务算法相同。任何真实 LLM 测试都要先确认模型、调用次数、成本和源码披露范围。

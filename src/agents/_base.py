"""
Agent 子系统公共基础设施

集中三处此前在每个 Agent / 流水线里复制粘贴的逻辑：

1. ``load_project_env()``      —— 加载仓库根目录 ``.env``（端点、密钥和模型分档）。
2. ``create_model_client()``   —— 构造 autogen_ext 的 OpenAIChatCompletionClient。
3. ``JsonLLMAgent``            —— RoutedAgent 基类，封装「原生 JSON mode → 严格解析与
   schema 校验 → 失败时使用同一模型修复一次」这一所有 Agent 一致的调用流程；
   各 Agent 只需提供 system prompt、构造 user prompt、把 dict 映射成自己的结果 dataclass。
4. ``run_agent_selftest()``    —— 单 Agent 独立自测的通用入口，替代各文件里近百行重复的
   ``if __name__ == "__main__"`` 样板。

核心判定/合成逻辑（提示词、打分阈值、结果字段、失败默认值）仍由各 Agent 自己持有，
本模块只抽取与业务无关的样板代码。
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Callable, Dict, Mapping, Optional, Sequence

from autogen_core import RoutedAgent
from autogen_ext.models.openai import OpenAIChatCompletionClient

from .base import BaseRoutedAgent, register_agent
from ..llm.client import create_model_client as _create_model_client
from ..llm.config import load_project_env
from ..llm.json_output import JsonOutputError, complete_json_object
from ..common.logging import get_logger

logger = get_logger(__name__)

def create_model_client(model: Optional[str] = None) -> OpenAIChatCompletionClient:
    """按环境变量创建共享客户端；未指定模型时固定使用低档模型。"""
    return _create_model_client(model=model)


async def complete_json(
    model_client: OpenAIChatCompletionClient,
    system_message: str,
    user_prompt: str,
    schema: Mapping[str, Any],
    log=logger,
) -> Optional[Dict[str, Any]]:
    """
    以原生 JSON mode 调用 LLM，严格解析并按 schema 校验。

    首次失败时由共享基础设施使用同一模型修复一次；再次失败返回 ``None``，
    由调用方决定业务回退值。日志不记录可能包含源码的完整响应。
    """
    try:
        return await complete_json_object(
            model_client,
            system_message,
            user_prompt,
            schema,
            logger=log,
        )
    except JsonOutputError as exc:
        log.error("LLM JSON 响应在单次修复后仍无效: %s", exc)
        return None


class JsonLLMAgent(BaseRoutedAgent):
    """
    返回 JSON 的 LLM Agent 基类。

    子类需在 ``__init__`` 中调用
    ``super().__init__(agent_name, system_message, model_client, response_schema)``，
    并在自己的 ``@message_handler`` 中：构造 user prompt → ``await self.ask_json(prompt)``
    → 把 dict（或 None）映射为本 Agent 的结果 dataclass。
    """

    def __init__(
        self,
        agent_name: str,
        system_message: str,
        model_client: OpenAIChatCompletionClient,
        response_schema: Mapping[str, Any],
    ):
        super().__init__(agent_name)
        self._model_client = model_client
        self._system_message = system_message
        self._response_schema = response_schema
        self._log = self.logger

    async def ask_json(self, user_prompt: str) -> Optional[Dict[str, Any]]:
        """调用 LLM 并返回解析后的 dict；失败返回 None。"""
        return await complete_json(
            self._model_client,
            self._system_message,
            user_prompt,
            self._response_schema,
            self._log,
        )


def run_agent_selftest(
    title: str,
    agent_name: str,
    agent_factory: Callable[[OpenAIChatCompletionClient], RoutedAgent],
    requests: Sequence[Any],
    model: Optional[str] = None,
) -> None:
    """
    单 Agent 独立自测通用入口（供各 Agent 模块的 ``__main__`` 复用）。

    Args:
        title: 打印标题
        agent_name: 注册用的 Agent 名称（与 AgentId 对应）
        agent_factory: 接收 model_client，返回 Agent 实例
        requests: 依次发送给 Agent 的请求 dataclass 列表
        model: 使用的 LLM 模型
    """
    import asyncio
    import os

    from autogen_core import AgentId, SingleThreadedAgentRuntime

    load_project_env()

    print("=" * 60)
    print(title)
    print("=" * 60)

    if not os.getenv("OPENAI_API_KEY"):
        print("\n❌ 错误: 未设置 OPENAI_API_KEY 环境变量")
        print("  export OPENAI_API_KEY='your-api-key'")
        print("  export OPENAI_BASE_URL='your-base-url'  # 可选")
        return

    async def _run() -> None:
        runtime = SingleThreadedAgentRuntime()
        model_client = create_model_client(model)
        await register_agent(
            runtime, agent_name, lambda: agent_factory(model_client)
        )
        runtime.start()
        try:
            for i, req in enumerate(requests, 1):
                print(f"\n--- 测试用例 {i} ---")
                print(f"请求: {req}")
                result = await runtime.send_message(
                    req, recipient=AgentId(agent_name, key="default")
                )
                print("结果:")
                pretty = asdict(result) if is_dataclass(result) else result
                if isinstance(pretty, dict):
                    for k, v in pretty.items():
                        print(f"  {k}: {v}")
                else:
                    print(f"  {pretty}")
        finally:
            await runtime.stop()
            await runtime.close()
            await model_client.close()

        print("\n" + "=" * 60)
        print("测试完成")
        print("=" * 60)

    asyncio.run(_run())

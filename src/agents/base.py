"""AutoGen RoutedAgent 与运行时注册的共享约定。"""

from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional

from autogen_core import AgentId, RoutedAgent, SingleThreadedAgentRuntime

from src.common.logging import get_logger
from src.llm import LLMClient, LLMConfig
from src.llm.json_output import complete_json_object


DEFAULT_AGENT_KEY = "default"
AgentFactory = Callable[[], RoutedAgent]


def default_agent_id(agent_type: str) -> AgentId:
    """返回指定 Agent 类型在项目内使用的默认地址。"""
    return AgentId(type=agent_type, key=DEFAULT_AGENT_KEY)


async def register_agent(
    runtime: SingleThreadedAgentRuntime,
    agent_type: str,
    factory: AgentFactory,
) -> None:
    """通过唯一支持的工厂 API 注册 RoutedAgent。"""
    await runtime.register_factory(agent_type, factory)


class BaseRoutedAgent(RoutedAgent):
    """提供共享日志和可选 LLM 封装的 RoutedAgent 基类。"""

    def __init__(
        self,
        description: str,
        llm_config: Optional[LLMConfig] = None,
    ) -> None:
        super().__init__(description)
        self.logger = get_logger(self.__class__.__module__)
        self.llm_client = LLMClient(llm_config) if llm_config else None

    async def call_llm(
        self,
        system_message: str,
        user_message: str,
        **kwargs,
    ) -> str:
        """使用一条系统消息和一条用户消息调用已配置的 LLM。"""
        if self.llm_client is None:
            raise ValueError(f"Agent {self.id.type} 未配置 LLM 客户端")
        return await self.llm_client.create(
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            **kwargs,
        )

    async def call_json(
        self,
        system_message: str,
        user_message: str,
        schema: Mapping[str, Any],
    ) -> Dict[str, Any]:
        """请求 JSON 对象，严格校验，并在失败时最多修复一次。"""
        if self.llm_client is None:
            raise ValueError(f"Agent {self.id.type} 未配置 LLM 客户端")
        return await complete_json_object(
            self.llm_client.model_client,
            system_message,
            user_message,
            schema,
            logger=self.logger,
            max_tokens=self.llm_client.config.max_tokens,
        )

    async def close_llm(self) -> None:
        """关闭此 Agent 持有的可选模型客户端。"""
        if self.llm_client is not None:
            await self.llm_client.close()

    async def close(self) -> None:
        """在 Runtime 关闭时释放此 Agent 持有的模型客户端。"""
        await self.close_llm()

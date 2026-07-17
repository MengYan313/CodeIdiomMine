"""Shared AutoGen RoutedAgent and runtime registration conventions."""

from __future__ import annotations

from typing import Callable, Optional

from autogen_core import AgentId, RoutedAgent, SingleThreadedAgentRuntime

from src.common.logging import get_logger
from src.llm import LLMClient, LLMConfig


DEFAULT_AGENT_KEY = "default"
AgentFactory = Callable[[], RoutedAgent]


def default_agent_id(agent_type: str) -> AgentId:
    """Return the project-wide default address for an Agent type."""
    return AgentId(type=agent_type, key=DEFAULT_AGENT_KEY)


async def register_agent(
    runtime: SingleThreadedAgentRuntime,
    agent_type: str,
    factory: AgentFactory,
) -> None:
    """Register a RoutedAgent through the single supported factory API."""
    await runtime.register_factory(agent_type, factory)


class BaseRoutedAgent(RoutedAgent):
    """RoutedAgent base with the shared logger and optional LLM wrapper."""

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
        """Call the configured LLM with one system and one user message."""
        if self.llm_client is None:
            raise ValueError(f"Agent {self.id.type} 未配置 LLM 客户端")
        return await self.llm_client.create(
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message},
            ],
            **kwargs,
        )

    async def close_llm(self) -> None:
        """Close the optional model client owned by this Agent."""
        if self.llm_client is not None:
            await self.llm_client.close()

    async def close(self) -> None:
        """Release the Agent-owned model client when its runtime closes."""
        await self.close_llm()

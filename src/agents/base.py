"""AutoGen Agent 的注册与结构化 LLM 调用。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Mapping, Optional, TypeVar

from autogen_core import AgentId, RoutedAgent, SingleThreadedAgentRuntime
from autogen_ext.models.openai import OpenAIChatCompletionClient

from src.common.logging import get_logger
from src.llm.json_output import JsonOutputError, complete_json_object


DEFAULT_AGENT_KEY = "default"
AgentFactory = Callable[[], RoutedAgent]
T = TypeVar("T")
JSON_MAX_ATTEMPTS = 2
JSON_RETRY_DELAY_SECONDS = 0.25
JSON_TIMEOUT_SECONDS = 120.0


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
    def __init__(self, description: str) -> None:
        super().__init__(description)
        self.logger = get_logger(self.__class__.__module__)


@dataclass(frozen=True)
class JsonCallTrace:
    status: str
    attempts: int
    failure_kind: str = ""


def agent_trace(result: Any, failure_action: str) -> dict[str, object]:
    return {
        "status": result.call_status,
        "logical_attempts": result.call_attempts,
        "failure_kind": result.failure_kind,
        "failure_action": (
            failure_action if result.call_status == "failed" else "continue"
        ),
    }


def not_run_trace(reason: str) -> dict[str, object]:
    return {
        "status": "not_run",
        "logical_attempts": 0,
        "failure_kind": reason,
        "failure_action": "skip_agent",
    }


async def dispatch_with_fallback(call: Awaitable[T], fallback: T) -> T:
    try:
        return await call
    except Exception:
        return fallback


class JsonLLMAgent(BaseRoutedAgent):
    """执行单次 JSON 修复和一次请求重试。"""

    def __init__(
        self,
        agent_name: str,
        system_message: str,
        model_client: OpenAIChatCompletionClient,
        response_schema: Mapping[str, Any],
    ) -> None:
        super().__init__(agent_name)
        self._model_client = model_client
        self._system_message = system_message
        self._response_schema = response_schema
        self._agent_name = agent_name
        self._last_call_trace = JsonCallTrace("not_started", 0)

    @property
    def last_call_trace(self) -> JsonCallTrace:
        return self._last_call_trace

    async def ask_json(self, user_prompt: str) -> Optional[Dict[str, Any]]:
        failure_kind = ""
        for attempt in range(1, JSON_MAX_ATTEMPTS + 1):
            try:
                data = await asyncio.wait_for(
                    complete_json_object(
                        self._model_client,
                        self._system_message,
                        user_prompt,
                        self._response_schema,
                        logger=self.logger,
                    ),
                    timeout=JSON_TIMEOUT_SECONDS,
                )
            except JsonOutputError:
                failure_kind = "json_invalid_after_repair"
            except Exception as exc:
                failure_kind = "request_error"
                self.logger.warning(
                    "%s 第 %d 次请求失败: %s",
                    self._agent_name,
                    attempt,
                    type(exc).__name__,
                )
            else:
                self._last_call_trace = JsonCallTrace("completed", attempt)
                return data

            if attempt < JSON_MAX_ATTEMPTS:
                await asyncio.sleep(JSON_RETRY_DELAY_SECONDS)

        self._last_call_trace = JsonCallTrace(
            "failed", JSON_MAX_ATTEMPTS, failure_kind
        )
        return None

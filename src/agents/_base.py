"""结构化 LLM Agent 的超时、修复、重试与调用状态。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Dict, Mapping, Optional, TypeVar

from autogen_ext.models.openai import OpenAIChatCompletionClient

from .base import BaseRoutedAgent
from ..llm.client import create_model_client as _create_model_client
from ..llm.json_output import JsonOutputError, complete_json_object


DEFAULT_JSON_AGENT_MAX_ATTEMPTS = 2
DEFAULT_JSON_AGENT_RETRY_DELAY_SECONDS = 0.25
DEFAULT_JSON_AGENT_TIMEOUT_SECONDS = 120.0

T = TypeVar("T")


@dataclass(frozen=True)
class JsonCallTrace:
    """单个 Agent 消息内的有界结构化调用结果。"""

    status: str
    attempts: int
    failure_kind: str = ""


def agent_trace(result: Any, failure_action: str) -> dict[str, object]:
    """把领域 Agent 结果映射为统一的可审计调用轨迹。"""

    return {
        "status": result.call_status,
        "logical_attempts": result.call_attempts,
        "failure_kind": result.failure_kind,
        "failure_action": (
            failure_action
            if result.call_status == "failed"
            else "continue"
        ),
    }


def not_run_trace(reason: str) -> dict[str, object]:
    """记录因上游门禁而未执行的 Agent。"""

    return {
        "status": "not_run",
        "logical_attempts": 0,
        "failure_kind": reason,
        "failure_action": "skip_agent",
    }


async def dispatch_with_fallback(
    call: Awaitable[T],
    fallback: T,
) -> T:
    """隔离单次 Runtime 路由异常，同时让取消和进程中断继续传播。"""

    try:
        return await call
    except Exception:
        return fallback


def create_model_client(model: Optional[str] = None) -> OpenAIChatCompletionClient:
    """按环境变量创建共享客户端；未指定模型时固定使用低档模型。"""
    return _create_model_client(model=model)


class JsonLLMAgent(BaseRoutedAgent):
    """执行带超时、单次 JSON 修复和一次有界重试的结构化调用。"""

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
        self._agent_name = agent_name
        self._last_call_trace = JsonCallTrace(
            status="not_started",
            attempts=0,
        )
        self._log = self.logger

    @property
    def last_call_trace(self) -> JsonCallTrace:
        """返回最近一条消息的调用状态，供领域结果保存审计证据。"""

        return self._last_call_trace

    async def ask_json(self, user_prompt: str) -> Optional[Dict[str, Any]]:
        """
        执行最多两次逻辑尝试；每次尝试内部仍只允许一次 JSON 修复。

        只有请求异常或 JSON 修复耗尽才重试。有效的业务拒绝不是技术失败，不会
        重试。全部尝试失败后返回 ``None``，由领域 Agent 选择拒绝、停止或跳过。
        """

        failure_kind = ""
        for attempt in range(1, DEFAULT_JSON_AGENT_MAX_ATTEMPTS + 1):
            try:
                data = await asyncio.wait_for(
                    complete_json_object(
                        self._model_client,
                        self._system_message,
                        user_prompt,
                        self._response_schema,
                        logger=self._log,
                    ),
                    timeout=DEFAULT_JSON_AGENT_TIMEOUT_SECONDS,
                )
            except JsonOutputError:
                failure_kind = "json_invalid_after_repair"
            except Exception as exc:
                failure_kind = "request_error"
                self._log.warning(
                    "Agent %s 第 %d 次逻辑尝试请求失败: %s",
                    self._agent_name,
                    attempt,
                    type(exc).__name__,
                )
            else:
                self._last_call_trace = JsonCallTrace(
                    status="completed",
                    attempts=attempt,
                )
                return data

            if attempt < DEFAULT_JSON_AGENT_MAX_ATTEMPTS:
                self._log.warning(
                    "Agent %s 第 %d 次逻辑尝试失败，将执行最后一次有界重试；"
                    "failure_kind=%s",
                    self._agent_name,
                    attempt,
                    failure_kind,
                )
                await asyncio.sleep(
                    DEFAULT_JSON_AGENT_RETRY_DELAY_SECONDS
                )

        self._last_call_trace = JsonCallTrace(
            status="failed",
            attempts=DEFAULT_JSON_AGENT_MAX_ATTEMPTS,
            failure_kind=failure_kind or "unknown_failure",
        )
        self._log.error(
            "Agent %s 在 %d 次逻辑尝试后失败；failure_kind=%s",
            self._agent_name,
            DEFAULT_JSON_AGENT_MAX_ATTEMPTS,
            self._last_call_trace.failure_kind,
        )
        return None

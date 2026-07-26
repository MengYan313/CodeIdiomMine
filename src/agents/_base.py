"""结构化 LLM Agent 的超时、修复、重试与调用状态。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

from autogen_ext.models.openai import OpenAIChatCompletionClient

from .base import BaseRoutedAgent
from ..llm.client import create_model_client as _create_model_client
from ..llm.json_output import JsonOutputError, complete_json_object


DEFAULT_JSON_AGENT_MAX_ATTEMPTS = 2
DEFAULT_JSON_AGENT_RETRY_DELAY_SECONDS = 0.25
DEFAULT_JSON_AGENT_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class JsonCallTrace:
    """单个 Agent 消息内的有界结构化调用结果。"""

    status: str
    attempts: int
    failure_kind: str = ""


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
        *,
        max_attempts: int = DEFAULT_JSON_AGENT_MAX_ATTEMPTS,
        retry_delay_seconds: float = DEFAULT_JSON_AGENT_RETRY_DELAY_SECONDS,
        request_timeout_seconds: float = DEFAULT_JSON_AGENT_TIMEOUT_SECONDS,
    ):
        super().__init__(agent_name)
        if int(max_attempts) < 1:
            raise ValueError("max_attempts 必须至少为 1")
        self._model_client = model_client
        self._system_message = system_message
        self._response_schema = response_schema
        self._agent_name = agent_name
        self._max_attempts = int(max_attempts)
        self._retry_delay_seconds = max(0.0, float(retry_delay_seconds))
        self._request_timeout_seconds = max(
            1.0,
            float(request_timeout_seconds),
        )
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
        for attempt in range(1, self._max_attempts + 1):
            try:
                data = await asyncio.wait_for(
                    complete_json_object(
                        self._model_client,
                        self._system_message,
                        user_prompt,
                        self._response_schema,
                        logger=self._log,
                    ),
                    timeout=self._request_timeout_seconds,
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

            if attempt < self._max_attempts:
                self._log.warning(
                    "Agent %s 第 %d 次逻辑尝试失败，将执行最后一次有界重试；"
                    "failure_kind=%s",
                    self._agent_name,
                    attempt,
                    failure_kind,
                )
                if self._retry_delay_seconds > 0:
                    await asyncio.sleep(self._retry_delay_seconds)

        self._last_call_trace = JsonCallTrace(
            status="failed",
            attempts=self._max_attempts,
            failure_kind=failure_kind or "unknown_failure",
        )
        self._log.error(
            "Agent %s 在 %d 次逻辑尝试后失败；failure_kind=%s",
            self._agent_name,
            self._max_attempts,
            self._last_call_trace.failure_kind,
        )
        return None

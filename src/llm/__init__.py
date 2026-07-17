"""
LLM 通用工具包

基于 AutoGen 的简洁 LLM 集成框架。
"""

from .config import AgentConfig, LLMConfig
from .client import LLMClient, create_model_client
from .message import MessageBuilder, MessageRole, ConversationHistory, Message
from .agent import BaseAgent, SimpleAgent, AgentTeam
from .utils import (
    retry_on_error,
    Timer
)
from .json_output import (
    JsonOutputError,
    complete_json_object,
    parse_json_object,
    validate_json_object,
)
from .prompting import build_json_system_prompt

__all__ = [
    # 配置
    'LLMConfig',
    'AgentConfig',

    # 客户端
    'LLMClient',
    'create_model_client',

    # 消息
    'MessageBuilder',
    'MessageRole',
    'ConversationHistory',
    'Message',

    # Agent 相关导出
    'BaseAgent',
    'SimpleAgent',
    'AgentTeam',

    # 工具
    'retry_on_error',
    'Timer',
    'JsonOutputError',
    'complete_json_object',
    'parse_json_object',
    'validate_json_object',
    'build_json_system_prompt',
]

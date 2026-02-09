"""
LLM 通用工具包

基于 AutoGen 的简洁 LLM 集成框架。
"""

from .config import LLMConfig, AgentConfig
from .client import LLMClient
from .message import MessageBuilder, MessageRole, ConversationHistory, Message
from .agent import BaseAgent, SimpleAgent, AgentTeam
from .utils import (
    retry_on_error, 
    parse_json_response,
    extract_code_blocks,
    Timer
)

__all__ = [
    # 配置
    'LLMConfig',
    'AgentConfig',
    
    # 客户端
    'LLMClient',
    
    # 消息
    'MessageBuilder',
    'MessageRole',
    'ConversationHistory',
    'Message',
    
    # Agent
    'BaseAgent',
    'SimpleAgent',
    'AgentTeam',
    
    # 工具
    'retry_on_error',
    'parse_json_response',
    'extract_code_blocks',
    'Timer',
]


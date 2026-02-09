"""
LLM 客户端模块

提供统一的 LLM 客户端接口，封装 AutoGen 的模型客户端。
纯异步实现，避免事件循环管理问题。
"""

import asyncio
from typing import List, Dict, Any, Optional, Union
from pathlib import Path
import json

from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_core.models import UserMessage, SystemMessage, AssistantMessage

from .config import LLMConfig
from .message import Message, MessageRole, MessageBuilder


class LLMClient:
    """
    LLM 客户端封装类（纯异步）
    
    提供简单易用的异步接口来调用 LLM 模型。
    
    示例:
        >>> import asyncio
        >>> config = LLMConfig(model="gpt-4o", temperature=0.7)
        >>> client = LLMClient(config)
        >>> response = await client.chat("你好，请介绍一下你自己")
        >>> print(response)
    """
    
    def __init__(self, config: LLMConfig):
        """
        初始化 LLM 客户端
        
        Args:
            config: LLM 配置对象
        """
        self.config = config
        self.config.validate()
        self._client = self._create_client()
    
    def _create_client(self) -> OpenAIChatCompletionClient:
        """创建底层的 AutoGen 客户端"""
        client_params = {
            'model': self.config.model,
            'api_key': self.config.api_key,
        }
        
        if self.config.base_url:
            client_params['base_url'] = self.config.base_url
        
        return OpenAIChatCompletionClient(**client_params)
    
    def _convert_messages_to_autogen_format(
        self,
        messages: List[Dict[str, Any]]
    ) -> List[Union[SystemMessage, UserMessage, AssistantMessage]]:
        """将消息转换为 AutoGen 格式"""
        autogen_messages = []
        
        for msg in messages:
            role = msg.get('role', 'user')
            content = msg.get('content', '')
            
            if role == 'system':
                autogen_messages.append(SystemMessage(content=content))
            elif role == 'user':
                autogen_messages.append(UserMessage(content=content, source='user'))
            elif role == 'assistant':
                autogen_messages.append(AssistantMessage(content=content, source='assistant'))
            else:
                # 默认作为用户消息
                autogen_messages.append(UserMessage(content=content, source='user'))
        
        return autogen_messages
    
    async def create(
        self,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: Optional[bool] = None,
        **kwargs
    ) -> str:
        """
        调用 LLM（异步）
        
        Args:
            messages: 消息列表（字典格式）
            temperature: 采样温度（覆盖配置）
            max_tokens: 最大 token 数（覆盖配置）
            json_mode: 是否启用 JSON 模式（覆盖配置）
            **kwargs: 其他参数
        
        Returns:
            LLM 响应文本
        """
        # 转换消息格式
        autogen_messages = self._convert_messages_to_autogen_format(messages)
        
        # 构建额外参数
        extra_args = {
            'temperature': temperature if temperature is not None else self.config.temperature,
        }
        
        # 只有明确指定 max_tokens 时才添加（None 表示使用模型默认最大值）
        final_max_tokens = max_tokens if max_tokens is not None else self.config.max_tokens
        if final_max_tokens is not None:
            extra_args['max_tokens'] = final_max_tokens
        
        # 如果启用 JSON 模式，添加 response_format
        use_json_mode = json_mode if json_mode is not None else self.config.json_mode
        if use_json_mode:
            extra_args['response_format'] = {'type': 'json_object'}
        
        extra_args.update(kwargs)
        
        # 调用 API
        response = await self._client.create(
            messages=autogen_messages,
            extra_create_args=extra_args
        )
        
        # 提取响应内容
        if hasattr(response, 'content'):
            return response.content
        else:
            return str(response)
    
    async def chat(
        self,
        prompt: str,
        system_message: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: Optional[bool] = None,
        **kwargs
    ) -> str:
        """
        简单的聊天接口（异步）
        
        Args:
            prompt: 用户提示词
            system_message: 可选的系统消息
            temperature: 采样温度（覆盖配置）
            max_tokens: 最大 token 数（覆盖配置）
            json_mode: 是否启用 JSON 模式（覆盖配置）
            **kwargs: 其他参数
        
        Returns:
            LLM 响应文本
        """
        # 构建消息
        builder = MessageBuilder()
        if system_message:
            builder.add_system_message(system_message)
        builder.add_user_message(prompt)
        messages = builder.build()
        
        # 调用异步方法
        return await self.create(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
            **kwargs
        )
    
    async def chat_with_history(
        self,
        messages: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: Optional[bool] = None,
        **kwargs
    ) -> str:
        """
        带历史记录的聊天（异步）
        
        Args:
            messages: 消息历史列表
            temperature: 采样温度（覆盖配置）
            max_tokens: 最大 token 数（覆盖配置）
            json_mode: 是否启用 JSON 模式（覆盖配置）
            **kwargs: 其他参数
        
        Returns:
            LLM 响应文本
        """
        return await self.create(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            json_mode=json_mode,
            **kwargs
        )
    
    async def batch_chat(
        self,
        prompts: List[str],
        system_message: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        json_mode: Optional[bool] = None,
        **kwargs
    ) -> List[str]:
        """
        批量聊天（异步并发）
        
        Args:
            prompts: 用户提示词列表
            system_message: 可选的系统消息
            temperature: 采样温度（覆盖配置）
            max_tokens: 最大 token 数（覆盖配置）
            json_mode: 是否启用 JSON 模式（覆盖配置）
            **kwargs: 其他参数
        
        Returns:
            LLM 响应文本列表
        """
        # 并发调用所有提示词
        tasks = [
            self.chat(
                prompt=prompt,
                system_message=system_message,
                temperature=temperature,
                max_tokens=max_tokens,
                json_mode=json_mode,
                **kwargs
            )
            for prompt in prompts
        ]
        
        responses = await asyncio.gather(*tasks)
        return list(responses)
    
    def get_config(self) -> LLMConfig:
        """获取当前配置"""
        return self.config
    



"""
LLM 配置模块

提供简洁的 LLM 配置管理，所有 API 配置通过环境变量读取。
"""

import os
from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class LLMConfig:
    """
    LLM 客户端配置
    
    属性:
        model: 模型名称，默认 "gpt-4o-mini"
        temperature: 采样温度，0.0-2.0，默认 0.0（确定性输出）
        max_tokens: 最大输出 token 数，默认 4096（设为 None 可使用模型最大值）
        json_mode: 是否启用 JSON 模式（强制返回有效 JSON），默认 False
        
    环境变量:
        OPENAI_API_KEY: API 密钥（必需）
        OPENAI_BASE_URL: API 端点（可选）
    
    注意：
        - 默认使用 gpt-4o-mini 模型（性价比高）
        - max_tokens=4096 适合大多数场景，设为 None 可使用模型最大输出能力
    """
    
    model: str = "gpt-4o-mini"
    temperature: float = 0.0
    max_tokens: Optional[int] = 4096
    json_mode: bool = False
    
    # 内部属性，自动从环境变量加载
    api_key: Optional[str] = field(default=None, init=False, repr=False)
    base_url: Optional[str] = field(default=None, init=False, repr=False)
    
    def __post_init__(self):
        """后初始化：从环境变量加载 API 配置"""
        self.api_key = self._load_api_key_from_env()
        self.base_url = self._load_base_url_from_env()
    
    def _load_api_key_from_env(self) -> Optional[str]:
        """从环境变量加载 API 密钥"""
        # 尝试常见的环境变量名称
        env_vars = [
            'OPENAI_API_KEY',
            'AZURE_OPENAI_API_KEY',
            'ANTHROPIC_API_KEY',
            'LLM_API_KEY',
        ]
        
        for var in env_vars:
            api_key = os.getenv(var)
            if api_key:
                return api_key
        
        return None
    
    def _load_base_url_from_env(self) -> Optional[str]:
        """从环境变量加载 base URL"""
        # 尝试常见的环境变量名称
        env_vars = [
            'OPENAI_BASE_URL',
            'OPENAI_API_BASE',
            'LLM_BASE_URL',
        ]
        
        for var in env_vars:
            base_url = os.getenv(var)
            if base_url:
                return base_url
        
        return None
    
    def __repr__(self) -> str:
        """字符串表示"""
        return (
            f"LLMConfig(model='{self.model}', "
            f"temperature={self.temperature}, "
            f"max_tokens={self.max_tokens})"
        )
    
    def validate(self) -> bool:
        """验证配置"""
        if not self.model:
            raise ValueError("模型名称是必需的")
        
        if not self.api_key:
            raise ValueError(
                "未找到 API 密钥。请设置环境变量 OPENAI_API_KEY\n"
                "示例: export OPENAI_API_KEY=your-api-key"
            )
        
        if self.temperature < 0 or self.temperature > 2:
            raise ValueError("temperature 必须在 0 到 2 之间")
        
        if self.max_tokens is not None and self.max_tokens <= 0:
            raise ValueError("max_tokens 必须为正数")
        
        return True


@dataclass
class AgentConfig:
    """
    Agent 配置
    
    属性:
        name: Agent 名称
        system_message: 系统消息/提示词
        llm_config: LLM 配置（可选，默认 gpt-4o）
    """
    
    name: str
    system_message: str
    llm_config: Optional[LLMConfig] = None
    
    def __post_init__(self):
        """后初始化：创建默认配置"""
        if self.llm_config is None:
            self.llm_config = LLMConfig()
    


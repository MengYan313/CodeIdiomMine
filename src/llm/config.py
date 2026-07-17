"""统一的项目本地 LLM 配置。

两个项目使用相同的 low、medium、high 模型档位，并从仓库根目录的 ``.env``
加载凭据，但不覆盖已导出的环境变量。业务代码应依赖 :class:`LLMConfig`，
不得直接读取模型或凭据变量。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]

MODEL_TIER_ENV_VARS = {
    "low": "OPENAI_MODEL_LOW",
    "medium": "OPENAI_MODEL_MEDIUM",
    "high": "OPENAI_MODEL_HIGH",
}

MODEL_TIER_DEFAULTS = {
    "low": "gpt-5.6-luna",
    "medium": "gpt-5.6-terra",
    "high": "gpt-5.6-sol",
}

MODEL_LOW_ENV = MODEL_TIER_ENV_VARS["low"]
MODEL_MEDIUM_ENV = MODEL_TIER_ENV_VARS["medium"]
MODEL_HIGH_ENV = MODEL_TIER_ENV_VARS["high"]
DEFAULT_MODEL_LOW = MODEL_TIER_DEFAULTS["low"]
DEFAULT_MODEL_MEDIUM = MODEL_TIER_DEFAULTS["medium"]
DEFAULT_MODEL_HIGH = MODEL_TIER_DEFAULTS["high"]

_ENV_LOADED = False


@dataclass(frozen=True)
class ModelTiers:
    """解析后的 low、medium、high 模型名称。"""

    low: str
    medium: str
    high: str


def load_project_env() -> None:
    """存在 dotenv 时，幂等加载仓库根目录的 ``.env``。"""
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    _ENV_LOADED = True

    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=False)


def get_model_tiers() -> ModelTiers:
    """解析所有模型档位，缺失时回退到共享的 GPT-5.6 默认值。"""
    load_project_env()
    return ModelTiers(
        low=os.getenv(MODEL_LOW_ENV) or DEFAULT_MODEL_LOW,
        medium=os.getenv(MODEL_MEDIUM_ENV) or DEFAULT_MODEL_MEDIUM,
        high=os.getenv(MODEL_HIGH_ENV) or DEFAULT_MODEL_HIGH,
    )


def resolve_model_tier(tier: str = "low") -> str:
    """解析一个指定名称的模型档位。"""
    normalized_tier = tier.lower()
    if normalized_tier not in MODEL_TIER_ENV_VARS:
        valid_tiers = ", ".join(MODEL_TIER_ENV_VARS)
        raise ValueError(f"未知模型档位: {tier}；可选值: {valid_tiers}")
    return getattr(get_model_tiers(), normalized_tier)


def resolve_model(model: Optional[str] = None, *, tier: str = "low") -> str:
    """使用显式模型，或解析指定档位（默认为 low）。"""
    return model or resolve_model_tier(tier)


def get_openai_model_info(model: str) -> Optional[Dict[str, Any]]:
    """为 AutoGen 0.7.5 尚未识别的中转模型名称补充能力信息。"""
    configured_models = set(get_model_tiers().__dict__.values())
    if not model.startswith("gpt-5.6") and model not in configured_models:
        return None
    return {
        "vision": True,
        "function_calling": True,
        "json_output": True,
        "family": "gpt-5",
        "structured_output": True,
        "multiple_system_messages": True,
    }


@dataclass
class LLMConfig:
    """共享异步 LLM 客户端配置。"""

    model: str = field(default_factory=resolve_model)
    temperature: float = 0.0
    max_tokens: Optional[int] = 4096
    json_mode: bool = False

    api_key: Optional[str] = field(default=None, init=False, repr=False)
    base_url: Optional[str] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        load_project_env()
        self.api_key = self._first_env(
            "OPENAI_API_KEY",
            "AZURE_OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "LLM_API_KEY",
        )
        self.base_url = self._first_env(
            "OPENAI_BASE_URL",
            "OPENAI_API_BASE",
            "LLM_BASE_URL",
        )

    @classmethod
    def for_tier(cls, tier: str = "low", **overrides: Any) -> "LLMConfig":
        """为指定档位创建配置，并允许覆盖可选字段。"""
        return cls(model=cls.model_for_tier(tier), **overrides)

    @classmethod
    def json_mode_config(cls, model: Optional[str] = None) -> "LLMConfig":
        """创建使用供应商原生 JSON mode 的确定性配置。"""
        return cls(
            model=model or cls.model_for_tier("low"),
            temperature=0.0,
            json_mode=True,
        )

    @staticmethod
    def model_for_tier(tier: str = "low") -> str:
        return resolve_model_tier(tier)

    @staticmethod
    def _first_env(*var_names: str) -> Optional[str]:
        for var_name in var_names:
            value = os.getenv(var_name)
            if value:
                return value
        return None

    def __repr__(self) -> str:
        return (
            f"LLMConfig(model='{self.model}', "
            f"temperature={self.temperature}, "
            f"max_tokens={self.max_tokens})"
        )

    def validate(self) -> bool:
        if not self.model:
            raise ValueError("模型名称是必需的")
        if not self.api_key:
            raise ValueError(
                "未找到 API 密钥。请设置环境变量 OPENAI_API_KEY\n"
                "示例: export OPENAI_API_KEY=your-api-key"
            )
        if not 0 <= self.temperature <= 2:
            raise ValueError("temperature 必须在 0 到 2 之间")
        if self.max_tokens is not None and self.max_tokens <= 0:
            raise ValueError("max_tokens 必须为正数")
        return True


@dataclass
class AgentConfig:
    """轻量对话 Agent 封装配置。"""

    name: str
    system_message: str
    llm_config: Optional[LLMConfig] = None

    def __post_init__(self) -> None:
        if self.llm_config is None:
            self.llm_config = LLMConfig()

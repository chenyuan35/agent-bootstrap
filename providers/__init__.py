from .base import ProviderAdapter, ProviderInfo
from .openai_adapter import OpenAIAdapter
from .anthropic_adapter import AnthropicAdapter
from .openrouter_adapter import OpenRouterAdapter

__all__ = [
    "ProviderAdapter",
    "ProviderInfo",
    "OpenAIAdapter",
    "AnthropicAdapter",
    "OpenRouterAdapter",
]


def get_provider(name: str):
    """获取 provider adapter 实例"""
    name_lower = name.lower()
    if name_lower in ("openai", "oai"):
        return OpenAIAdapter()
    elif name_lower in ("anthropic", "claude"):
        return AnthropicAdapter()
    elif name_lower in ("openrouter", "or"):
        return OpenRouterAdapter()
    raise ValueError(f"Unknown provider: {name}")
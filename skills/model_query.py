#!/usr/bin/env python3
"""Model Query Skill - 模型查询"""
import time
from typing import Dict, Any, Optional, List
from agent_bootstrap.cache.provider_cache import get_provider_cache


class ModelQuerySkill:
    """模型查询技能 - 识别模型能力、限制等"""
    def __init__(self):
        self.cache = get_provider_cache()
        # 已知模型能力数据库
        self.known_models = self._init_known_models()

    def _init_known_models(self) -> Dict[str, Dict[str, Any]]:
        """初始化已知模型信息"""
        return {
            # OpenAI
            "gpt-4": {
                "provider": "openai",
                "max_tokens": 8192,
                "vision": True,
                "function_calling": True,
                "reasoning": "high",
            },
            "gpt-4-1106-preview": {
                "provider": "openai",
                "max_tokens": 4096,
                "vision": True,
                "function_calling": True,
                "reasoning": "high",
            },
            "gpt-3.5-turbo": {
                "provider": "openai",
                "max_tokens": 4096,
                "vision": False,
                "function_calling": True,
                "reasoning": "medium",
            },
            # Anthropic
            "claude-3-5-sonnet-20241022": {
                "provider": "anthropic",
                "max_tokens": 8192,
                "vision": True,
                "reasoning": "high",
            },
            "claude-3-5-sonnet-20240620": {
                "provider": "anthropic",
                "max_tokens": 8192,
                "vision": True,
                "reasoning": "high",
            },
            "claude-3-opus-20240229": {
                "provider": "anthropic",
                "max_tokens": 4096,
                "vision": True,
                "reasoning": "highest",
            },
            "claude-3-sonnet-20240229": {
                "provider": "anthropic",
                "max_tokens": 4096,
                "vision": True,
                "reasoning": "high",
            },
            "claude-3-haiku-20240307": {
                "provider": "anthropic",
                "max_tokens": 4096,
                "vision": True,
                "reasoning": "medium",
                "fast": True,
            },
            # Google
            "gemini-1.5-pro": {
                "provider": "google",
                "max_tokens": 8192,
                "vision": True,
                "reasoning": "high",
            },
            "gemini-1.5-flash": {
                "provider": "google",
                "max_tokens": 8192,
                "vision": True,
                "reasoning": "medium",
                "fast": True,
            },
            # Cohere
            "command-r-plus": {
                "provider": "cohere",
                "max_tokens": 4096,
                "vision": False,
                "reasoning": "medium",
            },
        }

    def detect_model(self, model_name: str) -> Dict[str, Any]:
        """探测模型信息

        Args:
            model_name: 模型名称

        Returns:
            模型信息字典
        """
        # 1. 检查已知模型数据库
        if model_name in self.known_models:
            info = dict(self.known_models[model_name])
            info["source"] = "known_database"
            info["confidence"] = 1.0
            info["model"] = model_name
            return info

        # 2. 检查缓存
        cached = self.cache.get("unknown", model_name, "*")
        if cached:
            info = cached.to_dict()
            info["source"] = "cache"
            info["model"] = model_name
            return info

        # 3. 推断提供商
        provider = self._infer_provider(model_name)

        # 4. 返回推断结果
        info = {
            "model": model_name,
            "provider": provider,
            "source": "inferred",
            "confidence": 0.3,
            "max_tokens": 4096,  # 默认推测
            "vision": False,
        }

        # 更新缓存
        provider_knowledge = self.cache.get(provider, "*", "*")
        if provider_knowledge:
            # 合并provider级信息
            info.update({
                "inferred_from_provider": True,
                "provider_capabilities": provider_knowledge.capabilities,
            })

        return info

    def _infer_provider(self, model_name: str) -> str:
        """从模型名称推断提供商"""
        model_lower = model_name.lower()
        if "gpt" in model_lower or "o1" in model_lower:
            return "openai"
        elif "claude" in model_lower:
            return "anthropic"
        elif "gemini" in model_lower:
            return "google"
        elif any(x in model_lower for x in ["command", "cohere"]):
            return "cohere"
        elif "llama" in model_lower or "meta" in model_lower:
            return "meta"
        else:
            return "unknown"

    def infer_capabilities(self, model_name: str, provider: str) -> Dict[str, Any]:
        """推断模型能力（基于provider和命名模式）"""
        capabilities = {
            "max_tokens": 4096,
            "supports_vision": False,
            "supports_function_calling": False,
            "supports_tools": False,
            "supports_json_mode": False,
            "reasoning_level": "unknown",
        }

        # 基于provider默认值
        provider_defaults = {
            "openai": {
                "supports_function_calling": True,
                "supports_tools": True,
                "supports_json_mode": True,
            },
            "anthropic": {
                "supports_tools": True,
                "supports_json_mode": False,
            },
            "google": {
                "supports_tools": True,
                "supports_json_mode": True,
                "supports_vision": True,
            },
        }

        if provider in provider_defaults:
            capabilities.update(provider_defaults[provider])

        # 基于模型名称推断
        model_lower = model_name.lower()
        if "vision" in model_lower or "gpt-4v" in model_lower or "claude-3" in model_lower:
            capabilities["supports_vision"] = True

        if "gpt-4" in model_lower:
            capabilities["max_tokens"] = 8192
            capabilities["reasoning_level"] = "high"
        elif "o1" in model_lower:
            capabilities["max_tokens"] = 32768
            capabilities["reasoning_level"] = "very_high"
        elif "claude-3-5" in model_lower:
            capabilities["max_tokens"] = 8192
            capabilities["reasoning_level"] = "high"
        elif "claude-3-opus" in model_lower:
            capabilities["reasoning_level"] = "very_high"
        elif "haiku" in model_lower:
            capabilities["reasoning_level"] = "medium"
            capabilities["fast"] = True
        elif "flash" in model_lower:
            capabilities["reasoning_level"] = "medium"
            capabilities["fast"] = True
        elif "3.5" in model_lower or "turbo" in model_lower:
            capabilities["reasoning_level"] = "medium"

        return capabilities

    def list_known_models(self, provider: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出已知模型"""
        models = []
        for name, info in self.known_models.items():
            if provider is None or info.get("provider") == provider:
                models.append({"model": name, **info})
        return models

    def compare_models(self, model_names: List[str]) -> Dict[str, Any]:
        """比较多个模型的能力"""
        comparison = {}
        for name in model_names:
            comparison[name] = self.detect_model(name)
        return comparison

#!/usr/bin/env python3
"""Provider Adapter 基类 - 静态配置"""
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Set


@dataclass
class RateLimitRule:
    """速率限制规则"""
    requests_per_minute: Optional[int] = None
    requests_per_day: Optional[int] = None
    tokens_per_minute: Optional[int] = None
    tokens_per_day: Optional[int] = None
    concurrent_requests: Optional[int] = None
    rpm_model_specific: Dict[str, int] = field(default_factory=dict)
    tpm_model_specific: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "requests_per_minute": self.requests_per_minute,
            "requests_per_day": self.requests_per_day,
            "tokens_per_minute": self.tokens_per_minute,
            "tokens_per_day": self.tokens_per_day,
            "concurrent_requests": self.concurrent_requests,
            "rpm_model_specific": self.rpm_model_specific,
            "tpm_model_specific": self.tpm_model_specific,
        }


@dataclass
class ErrorSemantics:
    """错误语义定义"""
    rate_limit_codes: List[int] = field(default_factory=lambda: [429])
    quota_exhausted_codes: List[int] = field(default_factory=lambda: [402, 403])
    key_invalid_codes: List[int] = field(default_factory=lambda: [401])
    pattern_keywords: Dict[str, List[str]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rate_limit_codes": self.rate_limit_codes,
            "quota_exhausted_codes": self.quota_exhausted_codes,
            "key_invalid_codes": self.key_invalid_codes,
            "pattern_keywords": self.pattern_keywords,
        }


@dataclass
class ModelInfo:
    """模型信息"""
    name: str
    context_window: int = 4096
    max_output_tokens: int = 4096
    supports_function_calling: bool = False
    supports_vision: bool = False
    supports_tools: bool = False
    supports_json_mode: bool = False
    pricing_input_per_1m: Optional[float] = None
    pricing_output_per_1m: Optional[float] = None
    description: str = ""
    capabilities: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "supports_function_calling": self.supports_function_calling,
            "supports_vision": self.supports_vision,
            "supports_tools": self.supports_tools,
            "supports_json_mode": self.supports_json_mode,
            "pricing_input_per_1m": self.pricing_input_per_1m,
            "pricing_output_per_1m": self.pricing_output_per_1m,
            "description": self.description,
            "capabilities": self.capabilities,
        }


@dataclass
class ProviderInfo:
    """Provider 完整信息"""
    name: str
    base_url: str
    api_key_env: str
    website: str
    docs_url: str
    models: List[ModelInfo] = field(default_factory=list)
    rate_limit_rules: RateLimitRule = field(default_factory=RateLimitRule)
    error_semantics: ErrorSemantics = field(default_factory=ErrorSemantics)
    known_429_patterns: List[Dict[str, Any]] = field(default_factory=list)
    fallback_edges: List[str] = field(default_factory=list)
    last_web_refresh: float = 0.0
    ttl_seconds: int = 3600

    def is_expired(self) -> bool:
        return (time.time() - self.last_web_refresh) > self.ttl_seconds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "website": self.website,
            "docs_url": self.docs_url,
            "models": [m.to_dict() for m in self.models],
            "rate_limit_rules": self.rate_limit_rules.to_dict(),
            "error_semantics": self.error_semantics.to_dict(),
            "known_429_patterns": self.known_429_patterns,
            "fallback_edges": self.fallback_edges,
            "last_web_refresh": self.last_web_refresh,
            "is_expired": self.is_expired(),
        }


class ProviderAdapter(ABC):
    """Provider 适配器 - 静态配置"""

    def __init__(self):
        self.name = "base"
        self._cached_info: Optional[ProviderInfo] = None
        self._cache_ttl = 3600

    @abstractmethod
    def _build_static_info(self) -> ProviderInfo:
        """构建静态配置信息"""
        pass

    def get_models(self) -> List[ModelInfo]:
        info = self.get_provider_info()
        return info.models

    def get_rate_limit_rules(self, model_name: Optional[str] = None) -> RateLimitRule:
        info = self.get_provider_info()
        rules = info.rate_limit_rules
        if model_name and rules.rpm_model_specific:
            return RateLimitRule(
                requests_per_minute=rules.rpm_model_specific.get(model_name),
                tokens_per_minute=rules.tpm_model_specific.get(model_name),
                concurrent_requests=rules.concurrent_requests,
                requests_per_day=rules.requests_per_day,
                tokens_per_day=rules.tokens_per_day,
            )
        return rules

    def get_error_semantics(self) -> ErrorSemantics:
        info = self.get_provider_info()
        return info.error_semantics

    def get_provider_info(self) -> ProviderInfo:
        """获取完整 provider 信息"""
        if self._cached_info:
            return self._cached_info
        info = self._build_static_info()
        self._cached_info = info
        return info

    def get_fallback_models(self, current_model: str) -> List[str]:
        models = self.get_models()
        return [m.name for m in models if m.name != current_model]

    def model_exists(self, model_name: str) -> bool:
        return any(m.name == model_name for m in self.get_models())

    def to_dict(self) -> Dict[str, Any]:
        info = self.get_provider_info()
        return info.to_dict()
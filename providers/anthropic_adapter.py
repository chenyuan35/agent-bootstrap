#!/usr/bin/env python3
"""Anthropic Provider Adapter - 静态配置"""
from typing import Dict, Any, List

from .base import ProviderInfo, ModelInfo, RateLimitRule, ErrorSemantics, ProviderAdapter


class AnthropicAdapter(ProviderAdapter):
    """Anthropic 适配器 - 静态配置"""
    def __init__(self):
        super().__init__()
        self.name = "anthropic"
        self._cache_ttl = 3600

    def _build_static_info(self) -> ProviderInfo:
        return ProviderInfo(
            name="anthropic",
            base_url="https://api.anthropic.com",
            api_key_env="ANTHROPIC_API_KEY",
            website="https://anthropic.com",
            docs_url="https://docs.anthropic.com",
            models=self._get_known_models_static(),
            rate_limit_rules=self._get_known_rate_limits_static(),
            error_semantics=self._get_known_error_semantics_static(),
            known_429_patterns=[],
            fallback_edges=["openai", "openrouter"],
            last_web_refresh=0,
            ttl_seconds=3600,
        )

    def _get_known_models_static(self) -> List[ModelInfo]:
        return [
            ModelInfo(name="claude-3-5-sonnet-20241022", context_window=200000, max_output_tokens=8192,
                      supports_function_calling=False, supports_vision=True, supports_tools=True,
                      supports_json_mode=False, pricing_input_per_1m=3.0, pricing_output_per_1m=15.0,
                      description="Claude 3.5 Sonnet", capabilities={"vision": True, "tools": True, "reasoning": "high"}),
            ModelInfo(name="claude-3-opus-20240229", context_window=200000, max_output_tokens=4096,
                      supports_function_calling=False, supports_vision=True, supports_tools=True,
                      supports_json_mode=False, pricing_input_per_1m=15.0, pricing_output_per_1m=75.0,
                      description="Claude 3 Opus", capabilities={"vision": True, "tools": True, "reasoning": "highest"}),
            ModelInfo(name="claude-3-sonnet-20240229", context_window=200000, max_output_tokens=4096,
                      supports_function_calling=False, supports_vision=True, supports_tools=True,
                      supports_json_mode=False, pricing_input_per_1m=3.0, pricing_output_per_1m=15.0,
                      description="Claude 3 Sonnet", capabilities={"vision": True, "tools": True, "reasoning": "high"}),
            ModelInfo(name="claude-3-haiku-20240307", context_window=200000, max_output_tokens=4096,
                      supports_function_calling=False, supports_vision=True, supports_tools=True,
                      supports_json_mode=False, pricing_input_per_1m=0.25, pricing_output_per_1m=1.25,
                      description="Claude 3 Haiku", capabilities={"vision": True, "tools": True, "reasoning": "medium", "fast": True}),
        ]

    def _get_known_rate_limits_static(self) -> RateLimitRule:
        rpm_model = {"claude-3-5-sonnet-20241022": 4000, "claude-3-opus-20240229": 2000,
                     "claude-3-sonnet-20240229": 4000, "claude-3-haiku-20240307": 10000}
        tpm_model = {"claude-3-5-sonnet-20241022": 500000, "claude-3-opus-20240229": 200000,
                     "claude-3-sonnet-20240229": 500000, "claude-3-haiku-20240307": 1000000}
        return RateLimitRule(
            requests_per_minute=4000,
            tokens_per_minute=500000,
            concurrent_requests=50,
            rpm_model_specific=rpm_model,
            tpm_model_specific=tpm_model,
        )

    def _get_known_error_semantics_static(self) -> ErrorSemantics:
        return ErrorSemantics(
            rate_limit_codes=[429],
            quota_exhausted_codes=[402, 403],
            key_invalid_codes=[401],
            pattern_keywords={"rate_limit": ["rate limit", "too many requests"], "context": ["max_tokens", "context window"]},
        )
#!/usr/bin/env python3
"""OpenAI Provider Adapter - 静态配置"""
from typing import Dict, Any, List, Optional

from .base import ProviderInfo, ModelInfo, RateLimitRule, ErrorSemantics, ProviderAdapter


class OpenAIAdapter(ProviderAdapter):
    """OpenAI 适配器 - 静态配置"""
    def __init__(self):
        super().__init__()
        self.name = "openai"
        self._cache_ttl = 3600

    def _build_static_info(self) -> ProviderInfo:
        return ProviderInfo(
            name="openai",
            base_url="https://api.openai.com/v1",
            api_key_env="OPENAI_API_KEY",
            website="https://platform.openai.com",
            docs_url="https://platform.openai.com/docs/api-reference",
            models=self._get_known_models_static(),
            rate_limit_rules=self._get_known_rate_limits_static(),
            error_semantics=self._get_known_error_semantics_static(),
            known_429_patterns=[],
            fallback_edges=["anthropic", "openrouter"],
            last_web_refresh=0,
            ttl_seconds=3600,
        )

    def _get_known_models_static(self) -> List[ModelInfo]:
        return [
            ModelInfo(name="gpt-4o", context_window=128000, max_output_tokens=4096,
                      supports_function_calling=True, supports_vision=True, supports_tools=True,
                      supports_json_mode=True, pricing_input_per_1m=2.50, pricing_output_per_1m=10.00,
                      description="GPT-4o", capabilities={"vision": True, "reasoning": "high"}),
            ModelInfo(name="gpt-4o-mini", context_window=128000, max_output_tokens=16384,
                      supports_function_calling=True, supports_vision=True, supports_tools=True,
                      supports_json_mode=True, pricing_input_per_1m=0.15, pricing_output_per_1m=0.60,
                      description="GPT-4o-mini", capabilities={"vision": True, "reasoning": "medium"}),
            ModelInfo(name="gpt-4", context_window=8192, max_output_tokens=4096,
                      supports_function_calling=True, supports_tools=True, supports_json_mode=True,
                      pricing_input_per_1m=30.0, pricing_output_per_1m=60.0,
                      description="GPT-4", capabilities={"reasoning": "high"}),
            ModelInfo(name="gpt-3.5-turbo", context_window=16385, max_output_tokens=4096,
                      supports_function_calling=True, supports_tools=True, supports_json_mode=True,
                      pricing_input_per_1m=0.50, pricing_output_per_1m=1.50,
                      description="GPT-3.5 Turbo", capabilities={"reasoning": "medium"}),
        ]

    def _get_known_rate_limits_static(self) -> RateLimitRule:
        return RateLimitRule(
            requests_per_minute=10000,
            tokens_per_minute=500000,
            concurrent_requests=100,
            rpm_model_specific={"gpt-4o": 10000, "gpt-4o-mini": 15000, "gpt-4": 10000, "gpt-3.5-turbo": 15000},
            tpm_model_specific={"gpt-4o": 500000, "gpt-4o-mini": 1500000, "gpt-4": 500000, "gpt-3.5-turbo": 1500000},
        )

    def _get_known_error_semantics_static(self) -> ErrorSemantics:
        return ErrorSemantics(
            rate_limit_codes=[429],
            quota_exhausted_codes=[402, 403],
            key_invalid_codes=[401],
            pattern_keywords={"rate_limit": ["rate limit", "insufficient_quota"], "context": ["context_length"]},
        )
#!/usr/bin/env python3
"""OpenRouter Provider Adapter - 静态配置"""
from typing import Dict, Any, List

from .base import ProviderInfo, ModelInfo, RateLimitRule, ErrorSemantics, ProviderAdapter


class OpenRouterAdapter(ProviderAdapter):
    """OpenRouter 适配器 - 静态配置"""
    def __init__(self):
        super().__init__()
        self.name = "openrouter"
        self._cache_ttl = 3600

    def _build_static_info(self) -> ProviderInfo:
        return ProviderInfo(
            name="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key_env="OPENROUTER_API_KEY",
            website="https://openrouter.ai",
            docs_url="https://openrouter.ai/docs",
            models=self._get_known_models_static(),
            rate_limit_rules=self._get_known_rate_limits_static(),
            error_semantics=self._get_known_error_semantics_static(),
            known_429_patterns=[],
            fallback_edges=["anthropic", "openai"],
            last_web_refresh=0,
            ttl_seconds=3600,
        )

    def _get_known_models_static(self) -> List[ModelInfo]:
        return [
            ModelInfo(name="mistralai/devstral-2512", context_window=32000, max_output_tokens=8192,
                      supports_function_calling=True, supports_vision=False, supports_tools=True,
                      supports_json_mode=True, pricing_input_per_1m=0.14, pricing_output_per_1m=0.28,
                      description="Mistral Devstral 2512", capabilities={"tools": True, "reasoning": "medium"}),
            ModelInfo(name="openai/gpt-4o", context_window=128000, max_output_tokens=4096,
                      supports_function_calling=True, supports_vision=True, supports_tools=True,
                      supports_json_mode=True, pricing_input_per_1m=2.50, pricing_output_per_1m=10.00,
                      description="GPT-4o via OpenRouter", capabilities={"vision": True, "tools": True, "reasoning": "high"}),
            ModelInfo(name="anthropic/claude-3.5-sonnet", context_window=200000, max_output_tokens=8192,
                      supports_function_calling=False, supports_vision=True, supports_tools=True,
                      supports_json_mode=False, pricing_input_per_1m=3.00, pricing_output_per_1m=15.00,
                      description="Claude 3.5 Sonnet via OpenRouter", capabilities={"vision": True, "tools": True, "reasoning": "high"}),
        ]

    def _get_known_rate_limits_static(self) -> RateLimitRule:
        rpm_model = {"mistralai/devstral-2512": 5000, "openai/gpt-4o": 10000, "anthropic/claude-3.5-sonnet": 4000}
        tpm_model = {"mistralai/devstral-2512": 200000, "openai/gpt-4o": 500000, "anthropic/claude-3.5-sonnet": 500000}
        return RateLimitRule(
            requests_per_minute=5000,
            tokens_per_minute=200000,
            concurrent_requests=100,
            rpm_model_specific=rpm_model,
            tpm_model_specific=tpm_model,
        )

    def _get_known_error_semantics_static(self) -> ErrorSemantics:
        return ErrorSemantics(
            rate_limit_codes=[429],
            quota_exhausted_codes=[402, 403],
            key_invalid_codes=[401, 403],
            pattern_keywords={"rate_limit": ["rate limit", "too many requests"], "cost": ["credit", "balance", "quota"]},
        )
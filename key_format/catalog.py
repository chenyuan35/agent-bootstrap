#!/usr/bin/env python3
"""Key Format Catalog - 已授权凭证格式识别

AI管家识别自家钥匙：基于已知key格式前缀，识别已配置凭证所属服务商。

仅用于识别AI已持有并显式传入的凭证格式，仅做本地前缀匹配。
"""
import re
from typing import Dict, Any, Optional, List


# Authorized credential format database
# Records known provider key format patterns for AI to identify configured credentials
# COMPLIANCE: Financial payment & social account keys REMOVED.
# Only technical development API keys are retained.
_KEY_FORMAT_DB = {
    # ---- AI Model Series (12) ----
    "openai": {
        "patterns": [r"^sk-[a-z0-9]{48}$", r"^sk-proj-[A-Za-z0-9_-]{50,}$"],
        "provider": "openai",
        "description": "OpenAI API key",
        "families": ["openai", "chatgpt"],
    },
    "anthropic": {
        "patterns": [r"^sk-ant-[A-Za-z0-9]{43}$", r"^sk-ant-api-[A-Za-z0-9-_]{50,}$"],
        "provider": "anthropic",
        "description": "Anthropic Claude API key",
        "families": ["anthropic", "claude"],
    },
    "zhipu-glm": {
        "patterns": [r"^zp-[A-Za-z0-9]{32}$"],
        "provider": "zhipu",
        "description": "Zhipu AI GLM API key",
        "families": ["zhipu", "glm"],
    },
    "moonshot": {
        "patterns": [r"^sk-moonshot-[a-z0-9]{36}$"],
        "provider": "moonshot",
        "description": "Moonshot Kimi API key",
        "families": ["moonshot", "kimi"],
    },
    "yi": {
        "patterns": [r"^yi-[A-Za-z0-9]{32}$"],
        "provider": "lingyi",
        "description": "Lingyi Wanwu Yi API key",
        "families": ["lingyi", "yi"],
    },
    "mistral": {
        "patterns": [r"^mistral-[a-z0-9]{40}$"],
        "provider": "mistral",
        "description": "Mistral AI API key",
        "families": ["mistral"],
    },
    "cohere": {
        "patterns": [r"^co-[a-z0-9]{40}$"],
        "provider": "cohere",
        "description": "Cohere API key",
        "families": ["cohere"],
    },
    "baidu-wenxin": {
        "patterns": [r"^ernie-[A-Za-z0-9]{32}$", r"^bd-[A-Za-z0-9]{32}$"],
        "provider": "baidu",
        "description": "Baidu Wenxin Yiyan API key",
        "families": ["baidu", "wenxin"],
    },
    "xunfei-spark": {
        "patterns": [r"^spark-[A-Z0-9]{32}$", r"^xfsk-[A-Za-z0-9]{32}$"],
        "provider": "xunfei",
        "description": "iFlytek Spark API key",
        "families": ["xunfei", "spark"],
    },
    "baichuan": {
        "patterns": [r"^baichuan-[A-Za-z0-9]{32}$", r"^bc-[A-Za-z0-9]{32}$"],
        "provider": "baichuan",
        "description": "Baichuan AI API key",
        "families": ["baichuan"],
    },
    "deepseek": {
        "patterns": [r"^sk-[a-z0-9_]{49}$"],
        "provider": "deepseek",
        "description": "DeepSeek API key",
        "families": ["deepseek"],
    },
    "qwen": {
        "patterns": [r"^qwen-[A-Za-z0-9]{32}$"],
        "provider": "alibaba",
        "description": "Alibaba Tongyi Qianwen API key",
        "families": ["alibaba", "qwen"],
    },
    "dashscope": {
        "patterns": [r"^sk-[a-f0-9]{32}$"],
        "provider": "dashscope",
        "description": "Alibaba DashScope (Bailian) API key",
        "families": ["alibaba", "dashscope", "bailian"],
    },
    # ---- Global Cloud Vendors (8) ----
    "aws": {
        "patterns": [r"^AKIA[A-Z0-9]{16}$", r"^ASIA[A-Z0-9]{16}$"],
        "provider": "aws",
        "description": "AWS Access Key",
        "families": ["aws", "amazon"],
    },
    "aliyun": {
        "patterns": [r"^LTAI[A-Z0-9]{16}$"],
        "provider": "aliyun",
        "description": "Alibaba Cloud AccessKey",
        "families": ["aliyun", "alibaba"],
    },
    "tencent-cloud": {
        "patterns": [r"^AKID[A-Za-z0-9]{16}$"],
        "provider": "tencent",
        "description": "Tencent Cloud SecretId",
        "families": ["tencent"],
    },
    "huawei-cloud": {
        "patterns": [r"^AK[A-Z0-9]{18}$"],
        "provider": "huawei",
        "description": "Huawei Cloud Access Key",
        "families": ["huawei"],
    },
    "volcengine": {
        "patterns": [r"^AK[A-Za-z0-9]{18}$"],
        "provider": "bytedance",
        "description": "Volcano Engine/ByteDance Cloud Access Key",
        "families": ["bytedance", "volcengine"],
    },
    "azure": {
        "patterns": [r"^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$"],
        "provider": "azure",
        "description": "Microsoft Azure API key",
        "families": ["azure", "microsoft"],
    },
    "gcp": {
        "patterns": [r"^ya29\.[A-Za-z0-9_-]{80,}$", r"^AIzaSy[A-Za-z0-9_-]{33}$"],
        "provider": "gcp",
        "description": "Google Cloud Platform service account",
        "families": ["gcp", "google"],
    },
    "jinshan-cloud": {
        "patterns": [r"^KS[A-Z0-9]{18}$"],
        "provider": "jinshan",
        "description": "Kingsoft Cloud Access Key",
        "families": ["jinshan"],
    },
    "digitalocean": {
        "patterns": [r"^dop_[a-z0-9]{64}$"],
        "provider": "digitalocean",
        "description": "DigitalOcean API token",
        "families": ["digitalocean"],
    },
    # ---- ByteDance Series (3) ----
    "douyin-clientkey": {
        "patterns": [r"^tt[A-Za-z0-9]{18}$"],
        "provider": "bytedance",
        "description": "Douyin/TikTok Open Platform ClientKey",
        "families": ["bytedance", "douyin"],
    },
    "volcengine-open": {
        "patterns": [r"^tt[A-Za-z0-9]{18}$"],
        "provider": "bytedance",
        "description": "Volcano Engine Open Platform key",
        "families": ["bytedance", "volcengine"],
    },
    "volcengine-llm": {
        "patterns": [r"^[A-Za-z0-9]{32}$"],
        "provider": "bytedance",
        "description": "Volcano Engine LLM Service key",
        "families": ["bytedance", "volcengine-llm"],
    },
    # ---- Domestic Open Platforms (5) ----
    "kuaishou": {
        "patterns": [r"^ks-[A-Za-z0-9]{32}$", r"^ksopen-[A-Za-z0-9]{32}$"],
        "provider": "kuaishou",
        "description": "Kuaishou Open Platform key",
        "families": ["kuaishou"],
    },
    "weibo": {
        "patterns": [r"^[0-9]{16}$"],
        "provider": "weibo",
        "description": "Weibo Open Platform key",
        "families": ["weibo"],
    },
    "zhihu": {
        "patterns": [r"^[A-Za-z0-9]{24}$"],
        "provider": "zhihu",
        "description": "Zhihu Open Platform key",
        "families": ["zhihu"],
    },
    "bilibili": {
        "patterns": [r"^bilibili-[A-Z0-9]{28}$"],
        "provider": "bilibili",
        "description": "Bilibili Open Platform key",
        "families": ["bilibili"],
    },
    "xiaomi": {
        "patterns": [r"^mi-[A-Za-z0-9]{30}$"],
        "provider": "xiaomi",
        "description": "Xiaomi Open Platform key",
        "families": ["xiaomi"],
    },
    # ---- Universal Auth / Token (3) ----
    "jwt": {
        "patterns": [r"^eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\..+$"],
        "provider": "jwt",
        "description": "JSON Web Token",
        "families": ["jwt", "auth"],
    },
    "firebase": {
        "patterns": [r"^AIzaSy[A-Za-z0-9_-]{33}$"],
        "provider": "firebase",
        "description": "Firebase Cloud Messaging key",
        "families": ["firebase", "google"],
    },
    "cloudflare": {
        "patterns": [r"^CFP[A-Z0-9]{31}$"],
        "provider": "cloudflare",
        "description": "Cloudflare API token",
        "families": ["cloudflare"],
    },
    # ---- Existing additional providers (kept) ----
    "groq": {
        "patterns": [r"^gsk_[a-zA-Z0-9]{20,}$"],
        "provider": "groq",
        "description": "Groq API key",
        "families": ["groq"],
    },
    "together": {
        "patterns": [r"^[a-f0-9]{64}$"],
        "provider": "together",
        "description": "Together AI key",
        "families": ["together"],
    },
    "replicate": {
        "patterns": [r"^r8_[a-zA-Z0-9]{20,}$"],
        "provider": "replicate",
        "description": "Replicate API key",
        "families": ["replicate"],
    },
    "huggingface": {
        "patterns": [r"^hf_[a-zA-Z0-9]{20,}$"],
        "provider": "huggingface",
        "description": "Hugging Face token",
        "families": ["huggingface", "hf"],
    },
    "openrouter": {
        "patterns": [r"^sk-or-[a-zA-Z0-9]{20,}$"],
        "provider": "openrouter",
        "description": "OpenRouter API key",
        "families": ["openrouter"],
    },
    "local": {
        "patterns": [r"^[a-zA-Z0-9]{32,}$", r"^local_[a-zA-Z0-9]+$"],
        "provider": "local",
        "description": "Local development key",
        "families": ["local"],
    },
}



_PROVIDER_PREFIXES = {
    "openai": ["sk-", "sk-proj-"],
    "anthropic": ["sk-ant-"],
    "zhipu": ["zp-"],
    "moonshot": ["sk-moonshot-"],
    "yi": ["yi-"],
    "mistral": ["mistral-"],
    "cohere": ["co-"],
    "baidu": ["ernie-", "bd-"],
    "xunfei": ["spark-", "xfsk-"],
    "baichuan": ["baichuan-", "bc-"],
    "deepseek": ["sk-"],  # note: overlaps with openai
    "qwen": ["qwen-"],
    "dashscope": ["sk-"],
    "aws": ["AKIA", "ASIA"],
    "aliyun": ["LTAI"],
    "tencent": ["AKID"],
    "huawei": ["AK"],
    "bytedance": ["tt"],
    "azure": [],
    "gcp": ["ya29.", "AIzaSy"],
    "jinshan": ["KS"],
    "digitalocean": ["dop_"],
    "groq": ["gsk_"],
    "together": [],
    "replicate": ["r8_"],
    "huggingface": ["hf_"],
    "openrouter": ["sk-or-"],
    "jwt": ["eyJ"],
    "firebase": ["AIzaSy"],
    "cloudflare": ["CFP"],
    "kuaishou": ["ks-", "ksopen-"],
    "weibo": [],
    "zhihu": [],
    "bilibili": ["bilibili-"],
    "xiaomi": ["mi-"],
    "local": ["local_"],
}


def identify_by_prefix(api_key: str) -> Optional[str]:
    """Identify provider by key prefix (longest prefix wins).

    Args:
        api_key: Configured API key string

    Returns:
        Provider name, or None if no match

    Note:
        Format-only match; does not validate key or make network calls.
    """
    if not api_key or not isinstance(api_key, str):
        return None

    # Build provider -> patterns mapping
    provider_patterns = {}
    for name, entry in _KEY_FORMAT_DB.items():
        p = entry["provider"]
        if p not in provider_patterns:
            provider_patterns[p] = []
        provider_patterns[p].extend(entry.get("patterns", []))

    # Step 1: longest-prefix-first matching + regex verification
    all_prefixes = []
    for provider, prefixes in _PROVIDER_PREFIXES.items():
        for p in prefixes:
            if p:  # skip empty prefixes
                all_prefixes.append((len(p), p, provider))
    all_prefixes.sort(reverse=True)  # longest first

    for _, prefix, provider in all_prefixes:
        if api_key.startswith(prefix):
            # Verify with regex pattern
            patterns = provider_patterns.get(provider, [])
            for pattern in patterns:
                try:
                    if re.match(pattern, api_key):
                        return provider
                except re.error:
                    continue

    # Step 2: fallback to regex patterns in _KEY_FORMAT_DB
    for entry in _KEY_FORMAT_DB.values():
        for pattern in entry.get("patterns", []):
            try:
                if re.match(pattern, api_key):
                    return entry["provider"]
            except re.error:
                continue

    return None


def get_format_by_provider_name(provider_name: str) -> List[Dict[str, Any]]:
    """获取指定服务商的凭证格式信息"""
    return [
        {"name": name, **info}
        for name, info in _KEY_FORMAT_DB.items()
        if info["provider"] == provider_name
    ]


def get_formats_by_family(family: str) -> List[Dict[str, Any]]:
    """按产品家族获取凭证格式信息"""
    return [
        {"name": name, **info}
        for name, info in _KEY_FORMAT_DB.items()
        if family in info.get("families", [])
    ]


def provider_families() -> Dict[str, List[Dict[str, Any]]]:
    """获取格式分类目录"""
    taxonomy: Dict[str, List[Dict[str, Any]]] = {}
    for name, info in _KEY_FORMAT_DB.items():
        provider = info["provider"]
        if provider not in taxonomy:
            taxonomy[provider] = []
        taxonomy[provider].append({"name": name, **info})
    return taxonomy
#!/usr/bin/env python3
"""
Model Tester - Generic model testing via provider info.

AI already has the key and identified the provider.
This module provides a generic way to test any model
using the provider's own base_url and auth format.

Flow:
    key + provider → load provider info (base_url, auth) → test model
"""

import json
import time
from typing import Dict, Any, Optional, Tuple


def test_model(
    provider: str,
    api_key: str,
    model: str,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    """
    Generic model test. AI calls this with its own key.

    Args:
        provider: Provider name (from identify_by_prefix)
        api_key: The key AI already holds
        model: Model name to test
        timeout: Request timeout in seconds

    Returns:
        {
            "status": "ok" | "error",
            "provider": str,
            "model": str,
            "latency_ms": int,
            "status_code": int,
            "message": str,
        }
    """
    info = _get_provider_info(provider)
    if not info:
        return {
            "status": "error",
            "message": f"Unknown provider: {provider}",
            "provider": provider,
            "model": model,
        }

    # Build endpoint: try /v1/chat/completions first (most common)
    base = info.get("base_url", "").rstrip("/")
    endpoints_to_try = [
        f"{base}/v1/chat/completions",
        f"{base}/v1/models",
        base,
    ]

    headers = _build_headers(provider, api_key, info)

    # Minimal test payload
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 5,
    }

    try:
        import httpx
    except ImportError:
        return {
            "status": "error",
            "message": "httpx not installed",
            "provider": provider,
            "model": model,
        }

    start = time.time()
    for ep in endpoints_to_try:
        try:
            resp = httpx.post(
                ep,
                json=payload,
                headers=headers,
                timeout=timeout,
            )
            latency = int((time.time() - start) * 1000)
            return {
                "status": "ok" if 200 <= resp.status_code < 300 else "error",
                "provider": provider,
                "model": model,
                "endpoint": ep,
                "status_code": resp.status_code,
                "latency_ms": latency,
                "message": _truncate(resp.text, 200),
            }
        except Exception as e:
            continue

    latency = int((time.time() - start) * 1000)
    return {
        "status": "error",
        "provider": provider,
        "model": model,
        "status_code": 0,
        "latency_ms": latency,
        "message": "All endpoints failed",
    }


def fetch_models(
    provider: str,
    api_key: str,
    timeout: float = 15.0,
) -> Dict[str, Any]:
    """
    Generic model list fetch. AI calls this with its own key.

    Args:
        provider: Provider name
        api_key: The key AI already holds
        timeout: Request timeout

    Returns:
        {
            "status": "ok" | "error",
            "provider": str,
            "models": list,   # list of model name strings
            "raw": str,      # raw response text
        }
    """
    info = _get_provider_info(provider)
    if not info:
        return {"status": "error", "message": f"Unknown provider: {provider}"}

    base = info.get("base_url", "").rstrip("/")
    models_endpoint = f"{base}/v1/models"

    headers = _build_headers(provider, api_key, info)

    try:
        import httpx
        resp = httpx.get(models_endpoint, headers=headers, timeout=timeout)
        if 200 <= resp.status_code < 300:
            return {
                "status": "ok",
                "provider": provider,
                "models_endpoint": models_endpoint,
                "status_code": resp.status_code,
                "raw": resp.text[:2000],
            }
        return {
            "status": "error",
            "provider": provider,
            "status_code": resp.status_code,
            "message": resp.text[:200],
        }
    except Exception as e:
        return {"status": "error", "provider": provider, "message": str(e)}


def _get_provider_info(provider: str) -> Optional[Dict[str, Any]]:
    """Load provider info from adapters or yaml."""
    # Try adapter first
    adapter_map = {
        "openai": ("openai_adapter", "OpenAIAdapter"),
        "anthropic": ("anthropic_adapter", "AnthropicAdapter"),
    }
    if provider in adapter_map:
        mod_name, cls_name = adapter_map[provider]
        try:
            import importlib
            mod = importlib.import_module(f"agent_bootstrap.providers.{mod_name}")
            adapter = getattr(mod, cls_name)()
            info = adapter.get_provider_info()
            return {
                "base_url": info.base_url,
                "api_key_env": info.api_key_env,
                "auth_header": "Authorization",
                "auth_prefix": "Bearer",
            }
        except Exception:
            pass

    # Fallback: load from providers.yaml
    try:
        import os
        yaml_path = os.path.join(
            os.path.dirname(__file__),
            "providers",
            "providers.yaml",
        )
        import yaml
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)
        providers = data.get("providers", {})
        if provider in providers:
            p = providers[provider]
            return {
                "base_url": p.get("base_url", ""),
                "api_key_env": p.get("api_key_env", ""),
                "auth_header": "Authorization",
                "auth_prefix": "Bearer",
            }
    except Exception:
        pass

    return None


def _build_headers(
    provider: str,
    api_key: str,
    info: Dict[str, Any],
) -> Dict[str, str]:
    """Build auth headers from provider info."""
    headers = {"Content-Type": "application/json"}

    auth_header = info.get("auth_header", "Authorization")
    auth_prefix = info.get("auth_prefix", "Bearer")
    env_var = info.get("api_key_env", "")

    # Common patterns
    if "anthropic" in provider:
        headers["x-api-key"] = api_key
    elif "openrouter" in provider:
        headers["Authorization"] = f"Bearer {api_key}"
        headers["HTTP-Referer"] = "https://agent-bootstrap"
    else:
        # Default: Bearer token
        headers[auth_header] = f"{auth_prefix} {api_key}".strip()

    return headers


def _truncate(text: str, limit: int = 200) -> str:
    if not text or len(text) <= limit:
        return text
    return text[:limit] + "..."

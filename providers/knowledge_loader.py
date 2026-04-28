#!/usr/bin/env python3
"""Provider Knowledge Graph loader"""
import yaml
import os
from typing import Dict, Any, Optional


def load_providers_knowledge(yaml_path: str = None) -> Dict[str, Any]:
    """Load providers.yaml knowledge graph"""
    if yaml_path is None:
        yaml_path = os.path.join(os.path.dirname(__file__), "providers.yaml")
    try:
        with open(yaml_path, "r") as f:
            data = yaml.safe_load(f)
        return data
    except Exception as e:
        return {"error": str(e)}


def get_provider_fallbacks(provider_name: str, knowledge: Dict[str, Any]) -> list:
    """获取 provider 的 fallback 列表"""
    providers = knowledge.get("providers", {})
    info = providers.get(provider_name, {})
    return info.get("fallback_edges", [])


def get_error_category_map(knowledge: Dict[str, Any]) -> Dict[str, str]:
    """获取错误码到类别的映射"""
    return knowledge.get("knowledge_graph", {}).get("error_category_map", {})


def get_strategy_recommendations(error_category: str, knowledge: Dict[str, Any]) -> list:
    """获取给定错误类型的策略推荐优先级列表"""
    recs = knowledge.get("knowledge_graph", {}).get("strategy_recommendations", {})
    return recs.get(error_category, [])


def get_model_info(provider: str, model: str, knowledge: Dict[str, Any]) -> Optional[Dict]:
    """获取特定模型信息"""
    providers = knowledge.get("providers", {})
    info = providers.get(provider, {})
    for m in info.get("models", []):
        if m["name"] == model:
            return m
    return None


def get_rate_limit_for_model(provider: str, model: str, knowledge: Dict[str, Any]) -> Dict[str, Any]:
    """获取模型的速率限制（如果有特定配置）"""
    providers = knowledge.get("providers", {})
    info = providers.get(provider, {})
    rl = info.get("rate_limits", {})
    model_specific = rl.get("model_specific", {})
    if model in model_specific:
        return model_specific[model]
    # 返回默认
    return {
        "requests_per_minute": rl.get("requests_per_minute"),
        "tokens_per_minute": rl.get("tokens_per_minute"),
        "concurrent_requests": rl.get("concurrent_requests"),
    }

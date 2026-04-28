#!/usr/bin/env python3
"""Provider Knowledge Cache - caches provider docs/API info"""
import json
import time
import os
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from threading import Lock


@dataclass
class ProviderKnowledge:
    """Provider knowledge entry"""
    provider: str           # e.g. "openai", "anthropic", "gemini"
    model: str              # e.g. "gpt-4", "claude-3-5-sonnet"
    endpoint: str           # API endpoint
    fetched_at: float       # 获取时间
    ttl: float = 3600       # 过期时间(秒)

    # 能力信息
    capabilities: Dict[str, Any] = None  # e.g. {"max_tokens": 4096, "vision": True}

    # Rate limit规则
    rate_limit_rules: Dict[str, Any] = None  # {"requests_per_min": 60, "tokens_per_min": 10000}

    # 429相关信息
    error_429_patterns: List[Dict[str, Any]] = None  # 429的典型模式
    recommended_retry_after: Optional[float] = None

    # 元数据
    source_url: Optional[str] = None  # 文档来源URL
    source_type: str = "manual"  # "web_scraped" | "manual" | "inferred"

    # 置信度 (0-1)
    confidence: float = 0.5

    def __post_init__(self):
        if self.capabilities is None:
            self.capabilities = {}
        if self.rate_limit_rules is None:
            self.rate_limit_rules = {}
        if self.error_429_patterns is None:
            self.error_429_patterns = []

    def is_expired(self) -> bool:
        return (time.time() - self.fetched_at) > self.ttl

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["_expired"] = self.is_expired()
        return d


class ProviderCache:
    """Provider knowledge cache manager"""
    def __init__(self, cache_file: str = None):
        if cache_file is None:
            cache_file = os.path.join(
                Path.home(), ".openclaw", "workspace", "data", "provider_cache.json"
            )
        self.cache_file = Path(cache_file)
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self._data: Dict[str, ProviderKnowledge] = {}  # key -> ProviderKnowledge
        self._lock = Lock()
        self._load()

    def _make_key(self, provider: str, model: str = "*", endpoint: str = "*") -> str:
        """生成缓存key"""
        return f"{provider}::{model}::{endpoint}"

    def _load(self) -> None:
        """从文件加载缓存"""
        try:
            if self.cache_file.exists():
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                    for key, value in raw.items():
                        # 兼容旧格式
                        if isinstance(value, dict) and "provider" in value:
                            self._data[key] = ProviderKnowledge(**value)
        except Exception as e:
            print(f"[ProviderCache] load error: {e}")

    def _save(self) -> None:
        """保存缓存到文件"""
        try:
            with open(self.cache_file, "w", encoding="utf-8") as f:
                data = {}
                with self._lock:
                    for key, value in self._data.items():
                        data[key] = value.to_dict()
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[ProviderCache] save error: {e}")

    def set(self, knowledge: ProviderKnowledge) -> None:
        """设置缓存条目"""
        key = self._make_key(knowledge.provider, knowledge.model, knowledge.endpoint)
        with self._lock:
            self._data[key] = knowledge
            # 也存储泛化查询
            wildcard_key = self._make_key(knowledge.provider, "*", "*")
            if wildcard_key not in self._data or self._data[wildcard_key].confidence < knowledge.confidence:
                self._data[wildcard_key] = knowledge
        self._save()

    def get(self, provider: str, model: str = "*", endpoint: str = "*") -> Optional[ProviderKnowledge]:
        """获取缓存条目"""
        # 优先精确匹配
        key = self._make_key(provider, model, endpoint)
        with self._lock:
            if key in self._data:
                entry = self._data[key]
                if not entry.is_expired():
                    return entry
                else:
                    # 已过期，但仍返回（可能有用）但标记
                    return entry

            # 尝试泛化匹配
            key2 = self._make_key(provider, "*", "*")
            if key2 in self._data:
                entry = self._data[key2]
                if not entry.is_expired():
                    return entry
        return None

    def update_rate_limit(self, provider: str, model: str, endpoint: str,
                          rules: Dict[str, Any], confidence_boost: float = 0.1) -> None:
        """更新rate limit规则"""
        key = self._make_key(provider, model, endpoint)
        with self._lock:
            if key in self._data:
                entry = self._data[key]
                entry.rate_limit_rules.update(rules)
                entry.confidence = min(1.0, entry.confidence + confidence_boost)
                entry.fetched_at = time.time()
            else:
                entry = ProviderKnowledge(
                    provider=provider, model=model, endpoint=endpoint,
                    fetched_at=time.time(), rate_limit_rules=rules,
                    confidence=min(0.8, confidence_boost),
                )
                self._data[key] = entry
        self._save()

    def update_429_pattern(self, provider: str, model: str, endpoint: str,
                           pattern: Dict[str, Any], confidence_boost: float = 0.1) -> None:
        """记录429模式"""
        key = self._make_key(provider, model, endpoint)
        with self._lock:
            if key in self._data:
                entry = self._data[key]
                entry.error_429_patterns.append(pattern)
                entry.confidence = min(1.0, entry.confidence + confidence_boost)
            else:
                entry = ProviderKnowledge(
                    provider=provider, model=model, endpoint=endpoint,
                    fetched_at=time.time(),
                    error_429_patterns=[pattern],
                    confidence=0.5,
                )
                self._data[key] = entry
        self._save()

    def list_all(self) -> List[Dict[str, Any]]:
        """列出所有缓存条目"""
        with self._lock:
            return [v.to_dict() for v in self._data.values()]

    def clear_expired(self) -> int:
        """清理过期条目，返回清理数量"""
        with self._lock:
            expired_keys = [k for k, v in self._data.items() if v.is_expired()]
            for k in expired_keys:
                del self._data[k]
            if expired_keys:
                self._save()
            return len(expired_keys)


_global_cache: Optional[ProviderCache] = None


def get_provider_cache() -> ProviderCache:
    """获取全局Provider缓存实例"""
    global _global_cache
    if _global_cache is None:
        _global_cache = ProviderCache()
    return _global_cache

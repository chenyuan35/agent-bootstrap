#!/usr/bin/env python3
"""Contextual Bandit for adaptive 429 handling

集成 Provider Knowledge Graph 以增强决策。
"""
import math
import random
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
import hashlib
import json

from agent_bootstrap.providers.knowledge_loader import load_providers_knowledge, get_error_category_map, get_strategy_recommendations, get_rate_limit_for_model


# Global knowledge graph cache
_KNOWLEDGE_CACHE = None


def _get_knowledge() -> Dict[str, Any]:
    global _KNOWLEDGE_CACHE
    if _KNOWLEDGE_CACHE is None:
        _KNOWLEDGE_CACHE = load_providers_knowledge()
    return _KNOWLEDGE_CACHE


@dataclass
class BanditAction:
    """Bandit 动作"""
    name: str
    description: str
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BanditContext:
    """Bandit 上下文（状态）"""
    provider: str
    model: str
    error_type: str           # 429, timeout, connection_error, quota_exhausted
    retry_count: int          # 当前重试次数
    attempt: int              # 总尝试次数
    concurrency: int          # 当前并发数
    current_latency: float    # 当前延迟(ms)
    p95_latency: float        # 最近p95延迟
    recent_429_rate: float    # 最近429频率 (0-1)
    rate_limit_remaining: Optional[int] = None
    tokens_remaining: Optional[int] = None
    retry_after: Optional[float] = None
    feature_vector: Dict[str, float] = field(default_factory=dict)

    def compute_features(self) -> Dict[str, float]:
        """计算特征向量"""
        features: Dict[str, float] = {
            "retry_count": float(self.retry_count),
            "attempt": float(self.attempt),
            "concurrency": float(self.concurrency),
            "current_latency_log": math.log1p(self.current_latency),
            "p95_latency_log": math.log1p(self.p95_latency),
            "recent_429_rate": self.recent_429_rate,
            "is_429": 1.0 if self.error_type == "429" else 0.0,
            "is_timeout": 1.0 if self.error_type == "timeout" else 0.0,
            "is_quota": 1.0 if self.error_type == "quota_exhausted" else 0.0,
            "provider_openai": 1.0 if self.provider == "openai" else 0.0,
            "provider_anthropic": 1.0 if self.provider == "anthropic" else 0.0,
            "provider_openrouter": 1.0 if self.provider == "openrouter" else 0.0,
        }
        if self.rate_limit_remaining is not None:
            features["rate_limit_remaining_norm"] = min(1.0, max(0.0, self.rate_limit_remaining / 1000.0))
        if self.tokens_remaining is not None:
            features["tokens_remaining_norm"] = min(1.0, max(0.0, self.tokens_remaining / 100000.0))
        if self.retry_after is not None:
            features["retry_after_log"] = math.log1p(self.retry_after)
        self.feature_vector = features
        return features

    def feature_hash(self, n_buckets: int = 1000) -> int:
        """将上下文哈希到桶"""
        key_parts = [
            self.provider,
            self.error_type,
            str(min(self.retry_count, 10)),
            str(min(self.concurrency // 5, 20)),
            "high_lat" if self.current_latency > 5000 else "low_lat",
        ]
        key_str = "|".join(key_parts)
        return int(hashlib.md5(key_str.encode()).hexdigest(), 16) % n_buckets


class ThompsonSamplingBandit:
    """Thompson Sampling Bandit (Beta-Bernoulli) - with knowledge graph guidance"""
    def __init__(self, n_context_buckets: int = 1000):
        self.n_buckets = n_context_buckets
        self.buckets: Dict[int, Dict[str, Tuple[float, float]]] = {}
        self.action_stats: Dict[str, Dict[str, float]] = {}
        self.knowledge = _get_knowledge()
        self.lock = __import__("threading").Lock()

    def _ensure_bucket(self, bucket_id: int, action_names: List[str]):
        """确保桶存在"""
        if bucket_id not in self.buckets:
            self.buckets[bucket_id] = {}
        for a in action_names:
            if a not in self.buckets[bucket_id]:
                # Initialize prior from knowledge graph
                prior = self._get_prior_for_action(a)
                self.buckets[bucket_id][a] = (prior, prior)  # Beta(prior, prior) 对称先验
            if a not in self.action_stats:
                self.action_stats[a] = {"alpha_sum": prior, "beta_sum": prior, "count": 0, "reward_sum": 0.0}

    def _get_prior_for_action(self, action_name: str) -> float:
        """Set prior for action based on knowledge graph"""
        # 默认先验
        priors = {
            "retry_immediate": 1.0,   # 较不优先
            "retry_delay_2s": 1.5,
            "retry_delay_5s": 1.5,
            "reduce_concurrency_half": 2.0,   # 优先降并发
            "reduce_concurrency_quarter": 1.8,
            "tune_params": 1.2,
            "exponential_backoff": 1.8,
            "switch_model": 1.3,
        }
        return priors.get(action_name, 1.0)

    def select_action(self, context: BanditContext, available_actions: List[BanditAction]) -> BanditAction:
        """Select action: weighted sampling with knowledge graph"""
        features = context.compute_features()
        bucket = context.feature_hash(self.n_buckets)
        action_names = [a.name for a in available_actions]

        with self.lock:
            self._ensure_bucket(bucket, action_names)
            bucket_actions = self.buckets[bucket]

            # 从 Beta 分布采样
            samples = {}
            for a_name in action_names:
                alpha, beta = bucket_actions[a_name]
                samples[a_name] = random.betavariate(alpha, beta)

            # Apply knowledge graph recommendation weighting
            weighted = self._apply_knowledge_weighting(samples, context)

            # 选择加权后最大的
            best_name = max(weighted, key=weighted.get)

        for a in available_actions:
            if a.name == best_name:
                return a
        return available_actions[0]

    def _apply_knowledge_weighting(self, samples: Dict[str, float],
                                   context: BanditContext) -> Dict[str, float]:
        """Apply knowledge graph weight adjustment to sampling values"""
        error_cat_map = get_error_category_map(self.knowledge)
        error_cat = error_cat_map.get(context.error_type, "unknown")
        recs = get_strategy_recommendations(error_cat, self.knowledge)

        # 创建推荐优先级权重
        rec_weight = {}
        for idx, action_name in enumerate(recs):
            rec_weight[action_name] = 1.0 + (len(recs) - idx) * 0.3  # 优先级越高加成越大

        weighted = {}
        for a_name, val in samples.items():
            boost = rec_weight.get(a_name, 1.0)
            weighted[a_name] = val * boost

        return weighted

    def update_reward(self, context: BanditContext, action_name: str, reward: float):
        """更新奖励"""
        bucket = context.feature_hash(self.n_buckets)
        r = max(0.0, min(1.0, reward))

        with self.lock:
            if bucket not in self.buckets:
                # 回退全局统计
                if action_name not in self.action_stats:
                    self.action_stats[action_name] = {"alpha_sum": 1.0, "beta_sum": 1.0, "count": 0, "reward_sum": 0.0}
                s = self.action_stats[action_name]
                s["count"] += 1
                s["reward_sum"] += r
                s["alpha_sum"] += r
                s["beta_sum"] += (1.0 - r)
                return

            if action_name not in self.buckets[bucket]:
                prior = self._get_prior_for_action(action_name)
                self.buckets[bucket][action_name] = (prior, prior)

            alpha, beta = self.buckets[bucket][action_name]
            new_alpha = alpha + r
            new_beta = beta + (1.0 - r)
            self.buckets[bucket][action_name] = (new_alpha, new_beta)

            if action_name not in self.action_stats:
                self.action_stats[action_name] = {"alpha_sum": 1.0, "beta_sum": 1.0, "count": 0, "reward_sum": 0.0}
            s = self.action_stats[action_name]
            s["count"] += 1
            s["reward_sum"] += r
            s["alpha_sum"] += r
            s["beta_sum"] += (1.0 - r)

    def get_action_values(self, context: BanditContext, available_actions: List[BanditAction]) -> Dict[str, float]:
        """获取动作期望价值"""
        features = context.compute_features()
        bucket = context.feature_hash(self.n_buckets)
        action_names = [a.name for a in available_actions]

        with self.lock:
            self._ensure_bucket(bucket, action_names)
            bucket_actions = self.buckets[bucket]

            values = {}
            for a_name in action_names:
                alpha, beta = bucket_actions[a_name]
                expected = alpha / (alpha + beta) if (alpha + beta) > 0 else 0.5
                values[a_name] = expected
            return values

    def get_global_stats(self) -> Dict[str, Any]:
        """获取全局统计"""
        with self.lock:
            stats = {}
            for a_name, s in self.action_stats.items():
                count = s["count"]
                reward_sum = s["reward_sum"]
                alpha_sum = s["alpha_sum"]
                beta_sum = s["beta_sum"]
                stats[a_name] = {
                    "count": count,
                    "avg_reward": reward_sum / count if count > 0 else 0.0,
                    "expected_value": alpha_sum / (alpha_sum + beta_sum) if (alpha_sum + beta_sum) > 0 else 0.5,
                    "alpha": alpha_sum,
                    "beta": beta_sum,
                }
            return {
                "n_buckets": self.n_buckets,
                "active_buckets": len(self.buckets),
                "action_stats": stats,
            }

    def get_bucket_values(self, bucket_id: int, action_names: List[str]) -> Dict[str, float]:
        """获取桶价值"""
        with self.lock:
            if bucket_id not in self.buckets:
                return {a: 0.5 for a in action_names}
            bucket = self.buckets[bucket_id]
            values = {}
            for a in action_names:
                if a in bucket:
                    alpha, beta = bucket[a]
                    values[a] = alpha / (alpha + beta) if (alpha + beta) > 0 else 0.5
                else:
                    values[a] = 0.5
            return values


# 预定义策略动作
DEFAULT_ACTIONS = [
    BanditAction(name="retry_immediate", description="立即重试（无延迟）", params={"delay": 0.1, "type": "retry"}),
    BanditAction(name="retry_delay_2s", description="等待2秒后重试", params={"delay": 2.0, "type": "retry"}),
    BanditAction(name="retry_delay_5s", description="等待5秒后重试", params={"delay": 5.0, "type": "retry"}),
    BanditAction(name="reduce_concurrency_half", description="将并发减半", params={"factor": 0.5, "type": "concurrency"}),
    BanditAction(name="reduce_concurrency_quarter", description="将并发降至1/4", params={"factor": 0.25, "type": "concurrency"}),
    BanditAction(name="tune_params", description="Tune params (reduce tokens, etc.)", params={"token_factor": 0.8, "type": "tune"}),
    BanditAction(name="exponential_backoff", description="指数退避重试", params={"base": 2.0, "max_delay": 60, "type": "backoff"}),
    BanditAction(name="switch_model", description="切换到备选模型", params={"type": "model_switch"}),
]

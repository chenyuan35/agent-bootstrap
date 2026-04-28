#!/usr/bin/env python3
"""Self-Tune Skill - Self-tuning skill based on historical performance"""
import time
import statistics
from typing import Dict, Any, List, Optional
from collections import deque, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from agent_bootstrap.skills.adaptive_429 import Adaptive429Skill, StrategyType
from agent_bootstrap.signals.runtime_signal import (
    SignalType, emit_signal, get_signal_buffer
)
from agent_bootstrap.cache.provider_cache import get_provider_cache


@dataclass
class PerformanceMetric:
    """Performance metric record"""
    timestamp: float
    latency_ms: float
    success: bool
    strategy_used: Optional[str] = None
    tokens_used: int = 0
    error_type: Optional[str] = None


@dataclass
class TunedConfig:
    """Tuned configuration"""
    provider: str
    model: str
    max_concurrency: int = 10
    max_tokens: int = 4096
    temperature: float = 0.7
    timeout: int = 30
    retry_count: int = 3
    retry_strategy: str = "exponential_backoff"
    # Dynamic tuning flags
    adaptive_rate_limit: bool = True
    dynamic_concurrency: bool = True
    dynamic_tokens: bool = True
    # Runtime state
    last_adjusted: float = field(default_factory=time.time)
    adjustment_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "provider": self.provider,
            "model": self.model,
            "max_concurrency": self.max_concurrency,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "timeout": self.timeout,
            "retry_count": self.retry_count,
            "retry_strategy": self.retry_strategy,
            "adaptive_rate_limit": self.adaptive_rate_limit,
            "dynamic_concurrency": self.dynamic_concurrency,
            "dynamic_tokens": self.dynamic_tokens,
            "last_adjusted": self.last_adjusted,
            "adjustment_count": self.adjustment_count,
        }
        return d


class SelfTuneSkill:
    """Self-tuning skill - auto-adjusts config based on historical performance"""
    def __init__(self):
        self.adaptive_429 = Adaptive429Skill()
        self.cache = get_provider_cache()
        # Performance history
        self.metrics_history: Dict[str, deque] = defaultdict(
            lambda: deque(maxlen=1000)
        )
        # Current tuned configs
        self.tuned_configs: Dict[str, TunedConfig] = {}
        # Tuning thresholds
        self.thresholds = {
            "latency_p95_slow": 5000,    # 95th percentile latency > 5s
            "error_rate_high": 0.1,      # Error rate > 10%
            "concurrent_saturation": 0.8, # Concurrency usage > 80%
            "token_efficiency_low": 0.5,  # Token efficiency < 50%
        }
        # Tuning step sizes
        self.steps = {
            "concurrency_up": 5,
            "concurrency_down": 2,
            "tokens_up": 512,
            "tokens_down": 256,
            "temp_up": 0.1,
            "temp_down": 0.1,
        }

    def record_performance(self, metric: PerformanceMetric):
        """Record performance metric"""
        key = f"{metric.provider}:{metric.model}"
        self.metrics_history[key].append(metric)

    def get_recent_metrics(self, provider: str, model: str,
                          lookback_seconds: int = 300) -> List[PerformanceMetric]:
        """Get recent performance metrics"""
        key = f"{provider}:{model}"
        cutoff = time.time() - lookback_seconds
        return [m for m in self.metrics_history[key] if m.timestamp >= cutoff]

    def calculate_error_rate(self, provider: str, model: str,
                            lookback_seconds: int = 300) -> float:
        """Calculate recent error rate"""
        metrics = self.get_recent_metrics(provider, model, lookback_seconds)
        if not metrics:
            return 0.0
        errors = sum(1 for m in metrics if not m.success)
        return errors / len(metrics)

    def calculate_latency_stats(self, provider: str, model: str,
                               lookback_seconds: int = 300) -> Dict[str, float]:
        """Calculate latency statistics"""
        metrics = self.get_recent_metrics(provider, model, lookback_seconds)
        if not metrics:
            return {"p50": 0, "p95": 0, "p99": 0, "avg": 0}
        latencies = [m.latency_ms for m in metrics if m.success]
        if not latencies:
            return {"p50": 0, "p95": 0, "p99": 0, "avg": 0}
        latencies.sort()
        n = len(latencies)
        return {
            "p50": latencies[int(n * 0.5)],
            "p95": latencies[int(n * 0.95)],
            "p99": latencies[int(n * 0.99)],
            "avg": statistics.mean(latencies),
        }

    def get_tuned_config(self, provider: str, model: str) -> TunedConfig:
        """Get or create tuned config for provider/model"""
        key = f"{provider}:{model}"
        if key not in self.tuned_configs:
            self.tuned_configs[key] = TunedConfig(provider=provider, model=model)
        return self.tuned_configs[key]

    def analyze_patterns(self, provider: str, model: str) -> Dict[str, Any]:
        """Analyze performance patterns and detect degradation"""
        metrics = self.get_recent_metrics(provider, model, lookback_seconds=600)
        error_rate = self.calculate_error_rate(provider, model)
        latency_stats = self.calculate_latency_stats(provider, model)

        patterns = {
            "degrading": False,
            "stable": True,
            "improving": False,
            "symptoms": [],
        }

        # Check error rate
        if error_rate > self.thresholds["error_rate_high"]:
            patterns["degrading"] = True
            patterns["stable"] = False
            patterns["symptoms"].append(f"high_error_rate:{error_rate:.2%}")

        # Check latency
        if latency_stats["p95"] > self.thresholds["latency_p95_slow"]:
            patterns["degrading"] = True
            patterns["stable"] = False
            patterns["symptoms"].append(f"high_latency_p95:{latency_stats['p95']:.0f}ms")

        # Check recent trend (last 5 min vs previous 5 min)
        recent = self.get_recent_metrics(provider, model, lookback_seconds=300)
        older = [m for m in metrics if m.timestamp < time.time() - 300]
        if recent and older:
            recent_error = sum(1 for m in recent if not m.success) / len(recent)
            older_error = sum(1 for m in older if not m.success) / len(older)
            if recent_error > older_error * 1.5:
                patterns["degrading"] = True
                patterns["improving"] = False
                patterns["symptoms"].append("error_rate_increasing")

        return patterns

    def adjust_for_degradation(self, provider: str, model: str,
                               config: TunedConfig) -> TunedConfig:
        """Adjust configuration when degradation detected"""
        stats = self.calculate_latency_stats(provider, model)
        error_rate = self.calculate_error_rate(provider, model)

        adjustments_made = []

        # Increase timeout if latency is high
        if stats["p95"] > 3000 and config.timeout < 120:
            config.timeout = min(120, config.timeout + 10)
            adjustments_made.append(f"timeout+{config.timeout}s")

        # Reduce concurrency if saturation suspected
        if error_rate > 0.15 and config.max_concurrency > 1:
            config.max_concurrency = max(1, config.max_concurrency - self.steps["concurrency_down"])
            adjustments_made.append(f"concurrency-{config.max_concurrency}")

        # Reduce tokens for faster responses
        if stats["avg"] > 2000 and config.max_tokens > 512:
            config.max_tokens = max(512, config.max_tokens - self.steps["tokens_down"])
            adjustments_made.append(f"tokens-{config.max_tokens}")

        # Increase temperature for diversity (might help with cached responses)
        if config.temperature < 1.0:
            config.temperature = min(1.0, config.temperature + self.steps["temp_up"])
            adjustments_made.append(f"temp+{config.temperature}")

        config.last_adjusted = time.time()
        config.adjustment_count += 1

        return config

    def adjust_for_improvement(self, provider: str, model: str,
                               config: TunedConfig) -> TunedConfig:
        """Adjust configuration when things are going well"""
        error_rate = self.calculate_error_rate(provider, model)

        # Increase concurrency if error rate is low
        if error_rate < 0.05 and config.max_concurrency < 50:
            config.max_concurrency += self.steps["concurrency_up"]
            config.max_concurrency = min(50, config.max_concurrency)

        # Increase tokens if latency is good
        stats = self.calculate_latency_stats(provider, model)
        if stats["p95"] < 1000 and config.max_tokens < 8192:
            config.max_tokens += self.steps["tokens_up"]
            config.max_tokens = min(8192, config.max_tokens)

        # Lower temperature for more focused responses
        if config.temperature > 0.3 and error_rate < 0.02:
            config.temperature = max(0.3, config.temperature - self.steps["temp_down"])

        config.last_adjusted = time.time()
        if error_rate < 0.02:  # Significant improvement
            config.adjustment_count += 1

        return config

    def should_retune(self, provider: str, model: str) -> bool:
        """Check if retuning is needed"""
        config = self.get_tuned_config(provider, model)
        time_since_adjustment = time.time() - config.last_adjusted
        # Minimum 60 seconds between adjustments
        if time_since_adjustment < 60:
            return False

        patterns = self.analyze_patterns(provider, model)
        return patterns["degrading"] or patterns["improving"]

    def run_tuning_cycle(self, provider: str, model: str) -> Dict[str, Any]:
        """Run a complete tuning cycle"""
        config = self.get_tuned_config(provider, model)
        patterns = self.analyze_patterns(provider, model)

        result = {
            "provider": provider,
            "model": model,
            "patterns": patterns,
            "previous_config": config.to_dict(),
            "adjustment_made": False,
            "reason": "no_change_needed",
        }

        if not self.should_tune(provider, model):
            result["new_config"] = config.to_dict()
            return result

        if patterns["degrading"]:
            config = self.adjust_for_degradation(provider, model, config)
            result["reason"] = "degradation_detected"
            result["adjustment_made"] = True
            # Use adaptive 429 skill for strategy recommendation
            strategy_rec = self.adaptive_429.get_contextual_recommendation(
                provider, model, current_attempt=1
            )
            result["strategy_recommendation"] = strategy_rec
        elif patterns["improving"]:
            config = self.adjust_for_improvement(provider, model, config)
            result["reason"] = "improvement_detected"
            result["adjustment_made"] = True

        result["new_config"] = config.to_dict()
        return result

    def should_tune(self, provider: str, model: str) -> bool:
        """Check if tuning is needed (wrapper for should_retune)"""
        return self.should_retune(provider, model)

    def get_tuning_report(self) -> Dict[str, Any]:
        """Generate tuning report for all provider/model pairs"""
        report = {
            "timestamp": time.time(),
            "total_configs": len(self.tuned_configs),
            "configs": {},
            "429_skill_stats": self.adaptive_429.get_strategy_stats(),
        }

        for key, config in self.tuned_configs.items():
            provider, model = key.split(":", 1)
            metrics = self.get_recent_metrics(provider, model)
            error_rate = self.calculate_error_rate(provider, model)
            latency_stats = self.calculate_latency_stats(provider, model)

            report["configs"][key] = {
                "config": config.to_dict(),
                "metrics": {
                    "sample_count": len(metrics),
                    "error_rate": error_rate,
                    "latency_stats": latency_stats,
                },
                "patterns": self.analyze_patterns(provider, model),
            }

        return report

    def reset_config(self, provider: str, model: str):
        """Reset config to defaults"""
        key = f"{provider}:{model}"
        if key in self.tuned_configs:
            del self.tuned_configs[key]

    def reset_all(self):
        """Reset all configs and history"""
        self.tuned_configs.clear()
        self.metrics_history.clear()

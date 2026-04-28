
#!/usr/bin/env python3
"""
Adaptive 429 Defense (v3 - Gentle)

Three-layer defense:
  1. Exponential backoff (per request)
  2. Provider-level cooldown bucket (per-provider)
  3. Adaptive rate budget (auto-throttle when success rate drops)

Passive mode: only responds to upstream 429 signals.
"""
import time
import math
from dataclasses import dataclass, field
from typing import Dict, Optional

@dataclass
class ProviderState:
    cooldown_until: float = 0.0
    success_count: int = 0
    rate429_count: int = 0
    total_requests: int = 0
    window_start: float = field(default_factory=time.time)

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.rate429_count
        return self.success_count / total if total > 0 else 1.0

    def in_cooldown(self) -> bool:
        return time.time() < self.cooldown_until

    def reset_window_if_needed(self):
        now = time.time()
        if now - self.window_start > 60:  # 1分钟滑动窗口
            self.success_count = 0
            self.rate429_count = 0
            self.total_requests = 0
            self.window_start = now

class Adaptive429Handler:
    """
    单例处理器，供 orchestrator 调用
    """
    def __init__(self, base_delay: float = 2.0, max_delay: float = 60.0,
                 cooldown_factor: float = 5.0, low_rate_threshold: float = 0.5):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.cooldown_factor = cooldown_factor
        self.low_rate_threshold = low_rate_threshold

        self.provider_states: Dict[str, ProviderState] = {}

    def _get_state(self, provider: str) -> ProviderState:
        if provider not in self.provider_states:
            self.provider_states[provider] = ProviderState()
        return self.provider_states[provider]

    def on_429(self, provider: str, retry_count: int = 0) -> float:
        """
        遇到 429，返回建议 sleep 时间
        """
        state = self._get_state(provider)
        state.rate429_count += 1
        state.total_requests += 1

        # 1) 指数退避: base * 2^retry_count (有上限)
        delay = min(self.base_delay * (2 ** retry_count), self.max_delay)

        # 2) 如果连续多次 429，进入 Provider 级冷却桶
        if state.rate429_count >= 3:
            cooldown_sec = delay * self.cooldown_factor
            state.cooldown_until = time.time() + cooldown_sec
            print(f"  ⚠️  [{provider}] 触发冷却 {cooldown_sec:.0f}s (429×3)")

        return delay

    def on_success(self, provider: str):
        """
        请求成功，重置 429 计数并记录成功
        """
        state = self._get_state(provider)
        state.success_count += 1
        state.total_requests += 1
        # 成功时逐步缓解计数 (不清零，避免抖动)
        state.rate429_count = max(0, state.rate429_count - 1)

    def should_skip_provider(self, provider: str) -> bool:
        """
        检查该 provider 是否在冷却期内 (外部调用前检查)
        """
        state = self._get_state(provider)
        state.reset_window_if_needed()
        return state.in_cooldown()

    def get_adaptive_delay(self, provider: str) -> float:
        """
        基于成功率动态调整请求间隔
        成功率越低，间隔越大 (降频)
        """
        state = self._get_state(provider)
        rate = state.success_rate

        if rate < self.low_rate_threshold:
            return min(self.base_delay * 3, self.max_delay)
        elif rate < 0.7:
            return self.base_delay * 1.5
        return self.base_delay

    def get_stats(self) -> Dict[str, Dict]:
        """
        返回各 provider 统计 (用于遥测/监控)
        """
        stats = {}
        for p, s in self.provider_states.items():
            stats[p] = {
                "success_rate": round(s.success_rate, 3),
                "rate429_count": s.rate429_count,
                "total_requests": s.total_requests,
                "in_cooldown": s.in_cooldown(),
                "cooldown_until": s.cooldown_until,
            }
        return stats

# ── 全局单例 ──
_shared_429_handler = Adaptive429Handler()

def get_429_handler() -> Adaptive429Handler:
    return _shared_429_handler

#!/usr/bin/env python3
"""Adaptive 429 Strategy - Bandit-style adaptive strategy for rate limiting"""
import time
import random
import math
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from collections import defaultdict
import threading

from agent_bootstrap.bandit.strategy import BanditStrategy, EpsilonGreedyBandit
from agent_bootstrap.signals.runtime_signal import (
    SignalType, RuntimeSignal, emit_signal, get_signal_buffer
)


class StrategyType(Enum):
    RETRY_IMMEDIATE = "retry_immediate"      # immediate retry
    RETRY_DELAYED = "retry_delayed"          # delayed retry
    LOWER_CONCURRENCY = "lower_concurrency"  # lower concurrency
    SWITCH_MODEL = "switch_model"            # switch model
    TUNE_PARAMS = "tune_params"              # tune params (reduce tokens, etc.)
    BACKOFF_EXPONENTIAL = "backoff_exp"       # exponential backoff
    BACKOFF_LINEAR = "backoff_linear"        # linear backoff
    DO_NOTHING = "do_nothing"                # do nothing (wait)


@dataclass
class StrategyAction:
    """Strategy action definition"""
    strategy_type: StrategyType
    name: str
    description: str
    # action parameters
    params: Dict[str, Any] = field(default_factory=dict)
    # estimated success probability
    success_prob: float = 0.5
    # last used timestamp
    last_used: float = 0.0
    # usage count
    use_count: int = 0
    # success count
    success_count: int = 0

    @property
    def success_rate(self) -> float:
        if self.use_count == 0:
            return 0.0
        return self.success_count / self.use_count

    def apply(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Apply strategy, return modified context"""
        new_context = dict(context)

        if self.strategy_type == StrategyType.RETRY_IMMEDIATE:
            new_context["retry_immediate"] = True
            new_context["retry_delay"] = self.params.get("delay", 0.5)

        elif self.strategy_type == StrategyType.RETRY_DELAYED:
            delay = self.params.get("delay", 2.0)
            new_context["retry_delay"] = delay
            new_context["should_wait"] = True

        elif self.strategy_type == StrategyType.LOWER_CONCURRENCY:
            current = context.get("max_concurrency", 10)
            factor = self.params.get("factor", 0.5)
            new_context["max_concurrency"] = max(1, int(current * factor))

        elif self.strategy_type == StrategyType.SWITCH_MODEL:
            new_context["model"] = self.params.get("target_model", context.get("model"))
            new_context["switched_model"] = True

        elif self.strategy_type == StrategyType.TUNE_PARAMS:
            # reduce max_tokens
            if "max_tokens" in context:
                current = context["max_tokens"]
                factor = self.params.get("token_factor", 0.8)
                new_context["max_tokens"] = max(100, int(current * factor))
            # lower temperature
            if "temperature" in context:
                current = context["temperature"]
                factor = self.params.get("temp_factor", 0.8)
                new_context["temperature"] = max(0.0, min(2.0, current * factor))
            # add max_retries hint
            new_context["max_retries"] = self.params.get("max_retries", 2)

        elif self.strategy_type == StrategyType.BACKOFF_EXPONENTIAL:
            base = self.params.get("base", 2.0)
            new_context["backoff_multiplier"] = base
            new_context["use_exponential_backoff"] = True

        elif self.strategy_type == StrategyType.BACKOFF_LINEAR:
            step = self.params.get("step", 5.0)
            new_context["backoff_step"] = step
            new_context["use_linear_backoff"] = True

        elif self.strategy_type == StrategyType.DO_NOTHING:
            pass

        return new_context


@dataclass
class StrategyState:
    """Strategy usage state"""
    best_recent_action: Optional[str] = None
    consecutive_429: int = 0
    total_429_events: int = 0
    strategy_rewards: Dict[str, float] = field(default_factory=dict)


class VERIFYING_WEB:
    """Web verification states (for provider info)"""
    IDLE = "idle"
    FETCHING = "fetching"
    DONE = "done"


class Adaptive429Skill:
    """Adaptive strategy selector using bandit algorithms"""

    def __init__(self, strategy_type: str = "epsilon_greedy", window_size: int = 100):
        self.strategy_type = strategy_type
        self.window_size = window_size
        self.state = StrategyState()
        self.strategies = self._build_strategy_set()
        self.bandit = self._create_bandit()
        self.strategy_history: List[Dict[str, Any]] = []
        self._lock = threading.Lock()

    def _create_bandit(self) -> BanditStrategy:
        """Create bandit instance based on strategy type"""
        action_names = [s.name for s in self.strategies]
        if self.strategy_type == "epsilon_greedy":
            return EpsilonGreedyBandit(actions=action_names, epsilon=0.1, initial_value=0.5)
        else:
            return EpsilonGreedyBandit(actions=action_names, epsilon=0.1, initial_value=0.5)

    def _build_strategy_set(self) -> List[StrategyAction]:
        """Build available strategy set"""
        return [
            StrategyAction(
                strategy_type=StrategyType.RETRY_IMMEDIATE,
                name="retry_imm",
                description="Immediate retry with small delay",
                params={"delay": 0.5},
                success_prob=0.3,
            ),
            StrategyAction(
                strategy_type=StrategyType.RETRY_DELAYED,
                name="retry_delay",
                description="Retry after delay",
                params={"delay": 2.0},
                success_prob=0.5,
            ),
            StrategyAction(
                strategy_type=StrategyType.LOWER_CONCURRENCY,
                name="lower_conc",
                description="Reduce concurrency",
                params={"factor": 0.5},
                success_prob=0.4,
            ),
            StrategyAction(
                strategy_type=StrategyType.SWITCH_MODEL,
                name="switch_model",
                description="Switch to alternate model",
                params={"target_model": "fallback"},
                success_prob=0.6,
            ),
            StrategyAction(
                strategy_type=StrategyType.TUNE_PARAMS,
                name="tune_params",
                description="Tune request params",
                params={"token_factor": 0.8, "temp_factor": 0.8},
                success_prob=0.5,
            ),
            StrategyAction(
                strategy_type=StrategyType.BACKOFF_EXPONENTIAL,
                name="backoff_exp",
                description="Exponential backoff",
                params={"base": 2.0},
                success_prob=0.7,
            ),
            StrategyAction(
                strategy_type=StrategyType.BACKOFF_LINEAR,
                name="backoff_lin",
                description="Linear backoff",
                params={"step": 5.0},
                success_prob=0.6,
            ),
            StrategyAction(
                strategy_type=StrategyType.DO_NOTHING,
                name="wait",
                description="Wait and see",
                success_prob=0.2,
            ),
        ]

    def select_strategy(self, context: Dict[str, Any]) -> StrategyAction:
        """Select best strategy based on context and bandit"""
        with self._lock:
            action_name = self.bandit.select_action()
            strategy = next(s for s in self.strategies if s.name == action_name)

            # Heuristic overrides (bandit is overridden by heuristics)
            if context.get("is_429"):
                consecutive = self.state.consecutive_429
                if consecutive >= 3:
                    # Try model switch or exponential backoff
                    return next(s for s in self.strategies
                              if s.strategy_type in (StrategyType.SWITCH_MODEL,
                                                   StrategyType.BACKOFF_EXPONENTIAL))
                elif consecutive >= 1:
                    # Try delayed retry or lower concurrency
                    return next(s for s in self.strategies
                              if s.strategy_type in (StrategyType.RETRY_DELAYED,
                                                   StrategyType.LOWER_CONCURRENCY))

            if context.get("concurrent_requests", 1) > 5:
                return next(s for s in self.strategies
                          if s.strategy_type == StrategyType.LOWER_CONCURRENCY)

            return strategy

    def update_strategy_result(self, strategy_name: str, success: bool,
                               context: Dict[str, Any]):
        """Update strategy reward (bandit learning)"""
        with self._lock:
            strategy = next(s for s in self.strategies if s.name == strategy_name)
            strategy.use_count += 1
            if success:
                strategy.success_count += 1
                # Bandit update: positive reward
                reward = 1.0
            else:
                # Bandit update: negative reward
                reward = -0.5

            self.bandit.update(strategy_name, reward)

            # Update state
            record = {
                "timestamp": time.time(),
                "strategy": strategy_name,
                "success": success,
                "context": context,
                "reward": reward,
            }
            self.strategy_history.append(record)
            if len(self.strategy_history) > self.window_size:
                self.strategy_history.pop(0)

    def get_strategy_stats(self) -> Dict[str, Any]:
        """Get strategy statistics"""
        with self._lock:
            return {
                "total_selections": sum(s.use_count for s in self.strategies),
                "strategies": {
                    s.name: {
                        "use_count": s.use_count,
                        "success_count": s.success_count,
                        "success_rate": s.success_rate,
                        "estimated_value": self.bandit.get_action_value(s.name)
                              if hasattr(self.bandit, 'get_action_value')
                              else s.success_rate,
                    }
                    for s in self.strategies
                },
                "consecutive_429": self.state.consecutive_429,
                "total_429_events": self.state.total_429_events,
            }

    def handle_429_signal(self,
                         signal: RuntimeSignal,
                         request_context: Dict[str, Any]) -> StrategyAction:
        """Handle 429 signal and select appropriate strategy

        Args:
            signal: Runtime signal (contains 429 info)
            request_context: Current request context (provider, model, attempt, etc.)

        Returns:
            Selected strategy action
        """
        with self._lock:
            self.state.consecutive_429 += 1
            self.state.total_429_events += 1

        context = dict(request_context)
        context["is_429"] = True
        context["attempt"] = request_context.get("attempt", 1)

        strategy = self.select_strategy(context)

        # Apply exponential backoff base on consecutive 429s
        if strategy.strategy_type in (StrategyType.BACKOFF_EXPONENTIAL,
                                     StrategyType.BACKOFF_LINEAR):
            multiplier = min(2 ** (self.state.consecutive_429 - 1), 16)
            strategy.params["multiplier"] = multiplier

        return strategy

    def update_strategy_usage(self, strategy_name: str, success: bool):
        """Update strategy usage result (bandit learning)"""
        with self._lock:
            strategy = next(s for s in self.strategies if s.name == strategy_name)
            strategy.last_used = time.time()
            if success:
                self.state.consecutive_429 = max(0, self.state.consecutive_429 - 1)

    def get_contextual_recommendation(self, provider: str,
                                      model: str,
                                      current_attempt: int) -> Dict[str, Any]:
        """Get contextual strategy recommendation

        Args:
            provider: Provider name
            model: Model name
            current_attempt: Current retry attempt number

        Returns:
            Recommendation with strategy and parameters
        """
        context = {
            "provider": provider,
            "model": model,
            "attempt": current_attempt,
            "is_429": False,
        }

        strategy = self.select_strategy(context)

        return {
            "strategy": strategy.name,
            "type": strategy.strategy_type.value,
            "description": strategy.description,
            "params": strategy.params,
            "context_applied": context,
        }

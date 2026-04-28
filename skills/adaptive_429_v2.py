#!/usr/bin/env python3
"""Adaptive 429 V2 - Context-based adaptive strategy"""
import time
from typing import Dict, Any, Optional

from agent_bootstrap.policy.contextual_bandit import (
    ThompsonSamplingBandit, BanditAction, BanditContext,
    DEFAULT_ACTIONS as BANDIT_ACTIONS,
)
from agent_bootstrap.signals.runtime_signal import (
    SignalType, RuntimeSignal, emit_signal
)


class Adaptive429SkillV2:
    """Adaptive 429 Strategy V2 - Contextual bandit"""
    def __init__(self):
        self.bandit = ThompsonSamplingBandit(n_context_buckets=500)
        self.available_actions = BANDIT_ACTIONS
        self.state = "idle"
        self.last_context: Optional[BanditContext] = None
        self.last_action: Optional[BanditAction] = None

    def _build_context(self, signal: RuntimeSignal, request_context: Dict[str, Any]) -> BanditContext:
        """从信号和请求上下文构建 Bandit 上下文"""
        # 从请求上下文中提取信息
        recent_429_rate = 0.0
        # 可以通过 signal buffer 计算，这里简化
        details = signal.details or {}

        # 解析 rate limit 头部信息
        headers = details.get("headers", {})
        rate_limit_remaining = None
        tokens_remaining = None
        for k, v in headers.items():
            k_lower = k.lower()
            if "remaining-requests" in k_lower or "ratelimit-remaining" in k_lower:
                try:
                    rate_limit_remaining = int(v)
                except ValueError:
                    pass
            if "remaining-tokens" in k_lower or "token-limit" in k_lower:
                try:
                    tokens_remaining = int(v)
                except ValueError:
                    pass

        # 计算 p95 延迟（简化，这里用当前延迟）
        current_latency = request_context.get("latency_ms", 0.0)

        ctx = BanditContext(
            provider=request_context.get("provider", "unknown"),
            model=request_context.get("model", "unknown"),
            error_type=signal.signal_type.value,
            retry_count=request_context.get("attempt", 1) - 1,
            attempt=request_context.get("attempt", 1),
            concurrency=request_context.get("max_concurrency", 10),
            current_latency=current_latency,
            p95_latency=current_latency,  # 简化
            recent_429_rate=recent_429_rate,
            rate_limit_remaining=rate_limit_remaining,
            tokens_remaining=tokens_remaining,
            retry_after=signal.retry_after,
        )
        ctx.compute_features()
        return ctx

    def _apply_action(self, action: BanditAction, request_context: Dict[str, Any]) -> Dict[str, Any]:
        """应用动作，返回新的请求上下文"""
        new_ctx = dict(request_context)
        params = action.params

        if action.name == "retry_immediate":
            new_ctx["should_wait"] = False
            new_ctx["retry_delay"] = params.get("delay", 0.1)

        elif action.name == "retry_delay_2s":
            new_ctx["should_wait"] = True
            new_ctx["retry_delay"] = params.get("delay", 2.0)

        elif action.name == "retry_delay_5s":
            new_ctx["should_wait"] = True
            new_ctx["retry_delay"] = params.get("delay", 5.0)

        elif action.name == "reduce_concurrency_half":
            current = new_ctx.get("max_concurrency", 10)
            new_ctx["max_concurrency"] = max(1, int(current * params.get("factor", 0.5)))

        elif action.name == "reduce_concurrency_quarter":
            current = new_ctx.get("max_concurrency", 10)
            new_ctx["max_concurrency"] = max(1, int(current * params.get("factor", 0.25)))

        elif action.name == "tune_params":
            if "max_tokens" in new_ctx:
                new_ctx["max_tokens"] = int(new_ctx["max_tokens"] * params.get("token_factor", 0.8))
            if "temperature" in new_ctx:
                new_ctx["temperature"] = max(0.0, new_ctx["temperature"] * 0.8)

        elif action.name == "exponential_backoff":
            attempt = new_ctx.get("attempt", 1)
            base = params.get("base", 2.0)
            max_delay = params.get("max_delay", 60)
            delay = min(max_delay, base ** attempt)
            new_ctx["should_wait"] = True
            new_ctx["retry_delay"] = delay

        elif action.name == "switch_model":
            # 简单切换到同一提供商的下一个模型（实际中应有列表）
            new_ctx["model_switch_requested"] = True

        new_ctx["applied_bandit_action"] = action.name
        new_ctx["applied_action_desc"] = action.description

        return new_ctx

    def skill_handle_429(self, signal: RuntimeSignal,
                         request_context: Dict[str, Any]) -> Dict[str, Any]:
        """处理429 - 使用 Bandit 选择策略

        Args:
            signal: 429 信号
            request_context: 当前请求上下文

        Returns:
            处理结果
        """
        self.state = "processing"

        # 构建上下文
        ctx = self._build_context(signal, request_context)
        self.last_context = ctx

        # 选择动作
        action = self.bandit.select_action(ctx, self.available_actions)
        self.last_action = action

        # 应用动作
        new_ctx = self._apply_action(action, request_context)

        self.state = "adjusted"

        # 获取动作价值
        values = self.bandit.get_action_values(ctx, self.available_actions)

        return {
            "state": self.state,
            "selected_action": action.name,
            "action_description": action.description,
            "new_context": new_ctx,
            "action_values": values,
            "context_features": ctx.feature_vector,
        }

    def evaluate_result(self, reward: float):
        """评估上一次动作的结果

        Args:
            reward: 奖励值 (0-1之间)，1表示成功解决429
        """
        if self.last_context is None or self.last_action is None:
            return

        self.bandit.update_reward(
            self.last_context,
            self.last_action.name,
            reward
        )
        self.state = "evaluated"

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return {
            "state": self.state,
            "bandit_stats": self.bandit.get_global_stats(),
            "last_action": self.last_action.name if self.last_action else None,
        }

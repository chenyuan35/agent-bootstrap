#!/usr/bin/env python3
"""ProviderRouter - Deterministic provider routing

Weighted scoring strategy (simple, direct, no bandit):
    score = 0.5 * health_norm + 0.3 * budget_norm + 0.2 * latency_norm

Health first, budget second, latency third.
"""
import time
from typing import Dict, List, Optional, Tuple
from .controller import ProviderController, State


class ProviderRouter:
    """Multi-provider router"""
    def __init__(self,
                 weights: Tuple[float, float, float] = (0.5, 0.3, 0.2),
                 latency_window: float = 300.0):
        """
        Args:
            weights: (health_weight, budget_weight, latency_weight)
            latency_window: Latency stats window in seconds
        """
        self.weights = weights
        self.latency_window = latency_window
        self._latencies: Dict[str, List[Tuple[float, float]]] = {}  # provider -> [(ts, ms)]

    def register_provider(self, provider: str):
        if provider not in self._latencies:
            self._latencies[provider] = []

    def record_latency(self, provider: str, latency_ms: float):
        """Record latency for scoring"""
        now = time.time()
        if provider not in self._latencies:
            self._latencies[provider] = []
        self._latencies[provider].append((now, latency_ms))
        # Cleanup expired records
        cutoff = now - self.latency_window
        self._latencies[provider] = [(t, v) for t, v in self._latencies[provider] if t >= cutoff]

    def select(self,
               controllers: Dict[str, ProviderController],
               exclude: Optional[List[str]] = None) -> Optional[str]:
        """
        Select best available provider

        Returns: provider name, or None if no provider available
        """
        exclude = exclude or []
        candidates = {}

        for name, pc in controllers.items():
            if name in exclude:
                continue

            can_req, _ = pc.can_request()
            if not can_req:
                continue

            score = self._score_provider(pc, name)
            candidates[name] = score

        if not candidates:
            return None

        # Highest score wins
        return max(candidates, key=candidates.get)

    def _score_provider(self,
                        pc: ProviderController,
                        name: str) -> float:
        """Calculate provider score"""
        hw, bw, lw = self.weights

        # Health: 0-100 normalized to 0-1
        health_norm = pc.health / 100.0

        # Budget: normalized to 0-1 (capped at 100 for normalization)
        budget_norm = min(pc.rps_budget / 100.0, 1.0)

        # Latency: lower is better, normalized to 0-1
        avg_latency = self._avg_latency(name)
        if avg_latency > 0:
            # Inverse: lower latency = higher score
            latency_norm = min(1000.0 / avg_latency, 1.0)
        else:
            latency_norm = 1.0  # No latency data = neutral

        score = hw * health_norm + bw * budget_norm + lw * latency_norm
        return score

    def _avg_latency(self, provider: str) -> float:
        """Get average latency for provider"""
        if provider not in self._latencies:
            return 0.0
        records = self._latencies[provider]
        if not records:
            return 0.0
        return sum(v for _, v in records) / len(records)

    def rank(self, controllers: Dict[str, ProviderController]) -> List[Tuple[str, float]]:
        """Rank providers by score

        Returns: List of (provider, score) tuples sorted by score descending
        """
        ranked = []
        for name, pc in controllers.items():
            can_req, _ = pc.can_request()
            if not can_req:
                continue
            score = self._score_provider(pc, name)
            ranked.append((name, round(score, 4)))
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked

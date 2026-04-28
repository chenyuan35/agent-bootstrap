#!/usr/bin/env python3
"""Adaptive Strategy - Adaptive provider selection strategy"""
import math
import random
from typing import Dict, List, Optional
from abc import ABC, abstractmethod


class BanditStrategy(ABC):
    """Abstract bandit strategy base class"""
    @abstractmethod
    def select(self, actions: List[str]) -> str:
        """Select an action"""
        pass

    @abstractmethod
    def update(self, action: str, reward: float) -> None:
        """Update action value (receive reward)"""
        pass

    @abstractmethod
    def get_values(self) -> Dict[str, float]:
        """Get current value estimates for all actions"""
        pass


class EpsilonGreedyBandit(BanditStrategy):
    """Epsilon-Greedy strategy

    Explores with epsilon probability, exploits with (1-epsilon) probability.
    """
    def __init__(self, actions: List[str], epsilon: float = 0.3, initial_value: float = 0.5):
        self.epsilon = epsilon
        self.initial_value = initial_value
        self.values: Dict[str, float] = {}  # action -> value estimate
        self.counts: Dict[str, int] = {}   # action -> selection count
        for action in actions:
            self.register_action(action)

    def register_action(self, action: str, initial_value: Optional[float] = None) -> None:
        """Register an available action"""
        if action not in self.values:
            self.values[action] = initial_value if initial_value is not None else self.initial_value
            self.counts[action] = 0

    def select(self, actions: List[str]) -> str:
        """Select action"""
        for a in actions:
            if a not in self.values:
                self.register_action(a)
        if random.random() < self.epsilon:
            return random.choice(actions)
        else:
            best_value = max(self.values[a] for a in actions)
            best_actions = [a for a in actions if math.isclose(self.values[a], best_value)]
            return random.choice(best_actions)

    def update(self, action: str, reward: float) -> None:
        """Update action value based on received reward"""
        if action not in self.values:
            self.register_action(action)
        self.counts[action] += 1
        n = self.counts[action]
        old_value = self.values[action]
        self.values[action] = old_value + (reward - old_value) / n

    def get_values(self) -> Dict[str, float]:
        """Get current action values"""
        return dict(self.values)

    def get_action_value(self, action: str) -> float:
        """Get value for specific action"""
        return self.values.get(action, self.initial_value)


class UCB1Bandit(BanditStrategy):
    """Upper Confidence Bound (UCB1) strategy

    Balances exploration vs exploitation using confidence bounds.
    """
    def __init__(self, actions: List[str], initial_value: float = 0.5):
        self.initial_value = initial_value
        self.values: Dict[str, float] = {}
        self.counts: Dict[str, int] = {}
        self.total_counts = 0
        for action in actions:
            self.register_action(action)

    def register_action(self, action: str, initial_value: Optional[float] = None) -> None:
        """Register an available action"""
        if action not in self.values:
            self.values[action] = initial_value if initial_value is not None else self.initial_value
            self.counts[action] = 0

    def select(self, actions: List[str]) -> str:
        """Select action using UCB1 formula"""
        for a in actions:
            if a not in self.values:
                self.register_action(a)

        for a in actions:
            if self.counts[a] == 0:
                return a

        # UCB1: value + sqrt(2 * ln(total) / count)
        ucb_values = {}
        for a in actions:
            exploitation = self.values[a]
            exploration = math.sqrt(2 * math.log(self.total_counts) / self.counts[a])
            ucb_values[a] = exploitation + exploration

        return max(actions, key=lambda a: ucb_values[a])

    def update(self, action: str, reward: float) -> None:
        """Update action value"""
        if action not in self.values:
            self.register_action(action)
        self.total_counts += 1
        self.counts[action] += 1
        n = self.counts[action]
        old_value = self.values[action]
        self.values[action] = old_value + (reward - old_value) / n

    def get_values(self) -> Dict[str, float]:
        """Get current action values"""
        return dict(self.values)


class ThompsonSamplingBandit(BanditStrategy):
    """Thompson Sampling strategy (Beta-Bernoulli)

    Bayesian approach for exploration vs exploitation.
    """
    def __init__(self, actions: List[str], alpha_prior: float = 1.0, beta_prior: float = 1.0):
        self.alpha_prior = alpha_prior
        self.beta_prior = beta_prior
        self.alphas: Dict[str, float] = {}
        self.betas: Dict[str, float] = {}
        for action in actions:
            self.register_action(action)

    def register_action(self, action: str, alpha: Optional[float] = None, beta: Optional[float] = None) -> None:
        """Register an available action"""
        if action not in self.alphas:
            self.alphas[action] = alpha if alpha is not None else self.alpha_prior
            self.betas[action] = beta if beta is not None else self.beta_prior

    def select(self, actions: List[str]) -> str:
        """Select action using Thompson sampling"""
        for a in actions:
            if a not in self.alphas:
                self.register_action(a)

        samples = {}
        for a in actions:
            samples[a] = random.betavariate(self.alphas[a], self.betas[a])
        return max(actions, key=lambda a: samples[a])

    def update(self, action: str, reward: float) -> None:
        """Update Beta parameters based on reward (1=success, 0=failure)"""
        if action not in self.alphas:
            self.register_action(action)
        self.alphas[action] += reward
        self.betas[action] += (1.0 - reward)

    def get_values(self) -> Dict[str, float]:
        """Get current expected values"""
        values = {}
        for a in self.alphas:
            values[a] = self.alphas[a] / (self.alphas[a] + self.betas[a])
        return values

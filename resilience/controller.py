#!/usr/bin/env python3
"""ProviderController - 4-state table-driven resilience controller

States: HEALTHY -> LIMITED -> OPEN_CIRCUIT -> QUARANTINED
Events: SUCCESS, RATE_LIMIT, CAPACITY, AUTH_FAILURE, TIMEOUT
Core concept: All state transitions use TRANSITIONS table, side effects centralized.
"""
import time
import sqlite3
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum

from .classifier import classify, FailureClass


class State(Enum):
    HEALTHY = "healthy"
    LIMITED = "limited"
    OPEN_CIRCUIT = "open_circuit"
    QUARANTINED = "quarantined"


class Event(Enum):
    SUCCESS = "success"
    RATE_LIMIT = "rate_limit"
    CAPACITY = "capacity"
    AUTH_FAILURE = "auth_failure"
    TIMEOUT = "timeout"


# Table-driven transitions (current_state, event) -> next_state
TRANSITIONS = {
    (State.HEALTHY, Event.RATE_LIMIT): State.LIMITED,
    (State.HEALTHY, Event.CAPACITY): State.LIMITED,
    (State.HEALTHY, Event.AUTH_FAILURE): State.QUARANTINED,
    (State.HEALTHY, Event.TIMEOUT): State.LIMITED,
    (State.LIMITED, Event.RATE_LIMIT): State.OPEN_CIRCUIT,
    (State.LIMITED, Event.CAPACITY): State.OPEN_CIRCUIT,
    (State.LIMITED, Event.AUTH_FAILURE): State.QUARANTINED,
    (State.LIMITED, Event.SUCCESS): State.HEALTHY,
    (State.LIMITED, Event.TIMEOUT): State.OPEN_CIRCUIT,
    (State.OPEN_CIRCUIT, Event.SUCCESS): State.HEALTHY,
    (State.OPEN_CIRCUIT, Event.RATE_LIMIT): State.OPEN_CIRCUIT,
    (State.OPEN_CIRCUIT, Event.CAPACITY): State.OPEN_CIRCUIT,
    (State.OPEN_CIRCUIT, Event.AUTH_FAILURE): State.QUARANTINED,
    (State.OPEN_CIRCUIT, Event.TIMEOUT): State.OPEN_CIRCUIT,
    (State.QUARANTINED, Event.SUCCESS): State.HEALTHY,
    (State.QUARANTINED, Event.AUTH_FAILURE): State.QUARANTINED,
}


@dataclass
class ProviderRecord:
    name: str
    state: str = State.HEALTHY.value
    health: float = 100.0
    rps_budget: float = 10.0
    failure_count: int = 0
    cooldown_until: float = 0.0
    updated_at: float = 0.0


class ProviderController:
    """Single provider resilience controller"""

    def __init__(self,
                 name: str,
                 max_rps: float = 100.0,
                 min_rps: float = 1.0,
                 db_path: Optional[str] = None):
        self.name = name
        self.max_rps = max_rps
        self.min_rps = min_rps
        self.state: State = State.HEALTHY
        self.health: float = 100.0
        self.rps_budget: float = 10.0
        self.failure_count: int = 0
        self.cooldown_until: float = 0.0
        self.db_path = db_path
        self._last_retry_after: Optional[float] = None

    def transition(self, event: Event, retry_after: Optional[float] = None):
        """Table-driven state transition (unique state change entry point)"""
        if retry_after is not None:
            self._last_retry_after = retry_after
        key = (self.state, event)
        next_state = TRANSITIONS.get(key, self.state)
        if next_state != self.state:
            self._on_state_change(self.state, next_state)
            self.state = next_state
        self._apply_event_side_effects(event)

    def _on_state_change(self, old: State, new: State):
        """State change side effects"""
        now = time.time()
        if new == State.OPEN_CIRCUIT:
            duration = min(30.0 * (2 ** (self.failure_count // 3)), 600.0)
            self.cooldown_until = now + duration
        elif new == State.LIMITED:
            self.rps_budget = max(self.min_rps, self.rps_budget * 0.5)
        elif new == State.QUARANTINED:
            self.cooldown_until = now + 3600
        elif new == State.HEALTHY:
            self.cooldown_until = 0.0
            self._last_retry_after = None

    def _apply_event_side_effects(self, event: Event):
        """Numerical adjustments after each event"""
        if event == Event.SUCCESS:
            self.health = min(100.0, self.health + 1.0)
            self.failure_count = max(0, self.failure_count - 1)
            self.rps_budget = min(self.max_rps, self.rps_budget + 0.5)
        elif event == Event.RATE_LIMIT:
            self.health = max(0, self.health - 5)
            self.failure_count += 1
            self.rps_budget = max(self.min_rps, self.rps_budget * 0.5)
        elif event == Event.CAPACITY:
            self.health = max(0, self.health - 8)
            self.failure_count += 1
            self.rps_budget = max(self.min_rps, self.rps_budget * 0.6)
        elif event == Event.AUTH_FAILURE:
            self.health = max(0, self.health - 20)
            self.failure_count += 2
        elif event == Event.TIMEOUT:
            self.health = max(0, self.health - 3)
            self.failure_count += 1

    def can_request(self) -> tuple[bool, Optional[str]]:
        """Check if request can be sent"""
        now = time.time()
        if self.state == State.QUARANTINED:
            return False, "quarantined (auth/permission)"
        if self.state == State.OPEN_CIRCUIT:
            wait_until = self.cooldown_until
            if self._last_retry_after:
                wait_until = max(wait_until, now + self._last_retry_after)
            if now < wait_until:
                return False, f"circuit open ({wait_until - now:.0f}s)"
            self.state = State.LIMITED
            return True, None
        if self.state == State.LIMITED and self.rps_budget < self.min_rps:
            return False, "budget exhausted"
        return True, None

    def save(self, db_path: Optional[str] = None) -> None:
        path = db_path or self.db_path
        if not path:
            return
        conn = sqlite3.connect(path)
        conn.execute("""CREATE TABLE IF NOT EXISTS provider_state (
            name TEXT PRIMARY KEY, state TEXT, health REAL, rps_budget REAL,
            failure_count INTEGER, cooldown_until REAL, updated_at REAL)""")
        now = time.time()
        conn.execute("""
            INSERT OR REPLACE INTO provider_state
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (self.name, self.state.value, self.health, self.rps_budget,
             self.failure_count, self.cooldown_until, now))
        conn.commit()
        conn.close()

    @classmethod
    def load(cls, name: str, db_path: str, **kwargs) -> "ProviderController":
        pc = cls(name=name, db_path=db_path, **kwargs)
        conn = sqlite3.connect(db_path)
        conn.execute("""CREATE TABLE IF NOT EXISTS provider_state (
            name TEXT PRIMARY KEY, state TEXT, health REAL, rps_budget REAL,
            failure_count INTEGER, cooldown_until REAL, updated_at REAL)""")
        row = conn.execute(
            "SELECT state, health, rps_budget, failure_count, cooldown_until "
            "FROM provider_state WHERE name=?", (name,)
        ).fetchone()
        conn.close()
        if row:
            pc.state = State(row[0])
            pc.health, pc.rps_budget, pc.failure_count, pc.cooldown_until = row[1:]
        return pc

    def snapshot(self) -> Dict[str, Any]:
        now = time.time()
        remaining = max(0, self.cooldown_until - now) if self.cooldown_until > 0 else 0
        return {
            "name": self.name,
            "state": self.state.value,
            "health": round(self.health, 1),
            "rps_budget": round(self.rps_budget, 2),
            "failure_count": self.failure_count,
            "cooldown_remaining": round(remaining, 1),
            "can_request": self.can_request()[0],
        }

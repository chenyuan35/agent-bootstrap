#!/usr/bin/env python3
"""Bootstrap Orchestrator - 主调度器

状态机闭环：
    IDLE -> (请求) -> RUNNING
    RUNNING -> (429/异常) -> DETECTED -> SELECTING -> APPLYING -> ADJUSTED -> RUNNING
    RUNNING -> (成功) -> EVALUATING -> IDLE/ADJUSTED
"""
import time
import threading
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass
from enum import Enum

from agent_bootstrap.skills.adaptive_429 import Adaptive429Skill, StrategyType
from agent_bootstrap.skills.self_tune import SelfTuneSkill
from agent_bootstrap.signals.runtime_signal import (
    SignalType, RuntimeSignal, emit_signal, get_signal_buffer
)


class OrchestratorState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    DETECTED = "detected"
    SELECTING_STRATEGY = "selecting_strategy"
    APPLYING = "applying"
    ADJUSTED = "adjusted"
    EVALUATING = "evaluating"
    ERROR = "error"
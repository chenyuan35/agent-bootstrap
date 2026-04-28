#!/usr/bin/env python3
"""Runtime Signal Layer - 运行时事件信号"""
import time
import threading
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from enum import Enum
from collections import deque


class SignalType(Enum):
    RATE_LIMIT_429 = "429"
    KEY_RATE_LIMIT = "key_ratelimit"
    KEY_EXHAUSTED = "key_exhausted"
    KEY_INVALID = "key_invalid"
    CONNECTION_ERROR = "connection_error"
    TIMEOUT = "timeout"
    QUOTA_EXCEEDED = "quota_exceeded"


@dataclass
class RuntimeSignal:
    """运行时信号 - 封装异常信息"""
    signal_type: SignalType
    timestamp: float = field(default_factory=time.time)
    source: str = "unknown"  # provider/model/endpoint
    details: Dict[str, Any] = field(default_factory=dict)
    retry_after: Optional[float] = None  # 建议重试等待(秒)
    severity: int = 5  # 1-10, 越大越严重

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signal_type": self.signal_type.value,
            "timestamp": self.timestamp,
            "source": self.source,
            "details": self.details,
            "retry_after": self.retry_after,
            "severity": self.severity,
        }


class SignalBuffer:
    """环形信号缓冲区 - 记录最近的运行时信号"""
    def __init__(self, max_size: int = 100):
        self.buffer: deque[RuntimeSignal] = deque(maxlen=max_size)
        self.lock = threading.Lock()

    def push(self, signal: RuntimeSignal) -> None:
        with self.lock:
            self.buffer.append(signal)

    def recent(self, n: int = 10) -> List[RuntimeSignal]:
        with self.lock:
            return list(self.buffer)[-n:]

    def recent_by_type(self, signal_type: SignalType, n: int = 10) -> List[RuntimeSignal]:
        with self.lock:
            return [s for s in self.buffer if s.signal_type == signal_type][-n:]

    def frequency(self, window_seconds: float = 300) -> Dict[SignalType, int]:
        """统计窗口内信号频率"""
        cutoff = time.time() - window_seconds
        with self.lock:
            freq: Dict[SignalType, int] = {}
            for sig in self.buffer:
                if sig.timestamp >= cutoff:
                    freq[sig.signal_type] = freq.get(sig.signal_type, 0) + 1
            return freq


_signal_buffer = SignalBuffer()


def get_signal_buffer() -> SignalBuffer:
    """获取全局信号缓冲区"""
    return _signal_buffer


def emit_signal(signal_type: SignalType, source: str, details: Dict[str, Any] = None,
                retry_after: float = None, severity: int = 5) -> RuntimeSignal:
    """发射信号 - 供其他模块调用"""
    sig = RuntimeSignal(
        signal_type=signal_type,
        source=source,
        details=details or {},
        retry_after=retry_after,
        severity=severity,
    )
    _signal_buffer.push(sig)
    return sig

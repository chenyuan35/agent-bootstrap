
#!/usr/bin/env python3
"""
EventMonitor - Service event monitor

Provides generic service call event recording and statistics for health monitoring.
"""

import time
import threading
from typing import Dict, List, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict


@dataclass
class ServiceEvent:
    """Service call event"""
    service: str
    status_code: int
    latency_ms: float
    timestamp: float
    success: bool


class EventMonitor:
    """
    Service event monitor

    Records and analyzes service call events, generates health metrics.
    """

    def __init__(self, ttl: float = 3600.0):
        """
        Args:
            ttl: Event record time-to-live in seconds
        """
        self.ttl = ttl
        self._events: List[ServiceEvent] = []
        self._lock = threading.Lock()

        # Service stats: service -> {total, success, errors}
        self._stats: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"total": 0, "success": 0, "errors": 0}
        )

    def record_event(self,
                     service: str,
                     status_code: int,
                     latency_ms: float,
                     success: bool) -> None:
        """
        Record a service call event

        Args:
            service: Service name
            status_code: HTTP status code
            latency_ms: Latency in milliseconds
            success: Whether the call succeeded
        """
        with self._lock:
            # Clean up expired events
            self._cleanup_expired()

            event = ServiceEvent(
                service=service,
                status_code=status_code,
                latency_ms=latency_ms,
                timestamp=time.time(),
                success=success,
            )
            self._events.append(event)

            # Update stats
            self._stats[service]["total"] += 1
            if success:
                self._stats[service]["success"] += 1
            else:
                self._stats[service]["errors"] += 1

    def get_service_stats(self, service: str) -> Optional[Dict[str, float]]:
        """
        Get service statistics

        Returns:
            Dict with success_rate, avg_latency, error_rate
        """
        with self._lock:
            self._cleanup_expired()

            if service not in self._stats:
                return None

            stats = self._stats[service]
            total = stats["total"]

            if total == 0:
                return None

            # Calculate average latency for recent events
            recent_events = [e for e in self._events if e.service == service]
            avg_latency = (
                sum(e.latency_ms for e in recent_events) / len(recent_events)
                if recent_events
                else 0.0
            )

            return {
                "total_requests": total,
                "success_rate": round(stats["success"] / total, 4),
                "error_rate": round(stats["errors"] / total, 4),
                "avg_latency_ms": round(avg_latency, 1),
                "recent_events": len(recent_events),
            }

    def get_all_stats(self) -> Dict[str, Dict[str, float]]:
        """Get statistics for all services"""
        with self._lock:
            self._cleanup_expired()
            return {
                service: stats
                for service, stats in (
                    (s, self.get_service_stats(s))
                    for s in list(self._stats.keys())
                )
                if stats is not None
            }

    def _cleanup_expired(self) -> None:
        """Clean up expired events"""
        cutoff = time.time() - self.ttl
        old_count = len(self._events)

        # Keep only non-expired events
        self._events = [e for e in self._events if e.timestamp >= cutoff]

        # Rebuild stats if any events expired
        if old_count != len(self._events):
            self._rebuild_stats()

    def _rebuild_stats(self) -> None:
        """Rebuild statistics from current events"""
        self._stats.clear()
        for event in self._events:
            self._stats[event.service]["total"] += 1
            if event.success:
                self._stats[event.service]["success"] += 1
            else:
                self._stats[event.service]["errors"] += 1


#!/usr/bin/env python3
"""
Anonymous Telemetry (Opt-in)
- Disabled by default
- Only collects when user explicitly enables
- Never collects: API keys, prompts, outputs, user content
- Only collects: signal-level stats (provider, model, status, latency, 429 flag)
"""
import json
import os
import time
import uuid
from dataclasses import dataclass, asdict
from typing import List, Optional, Dict

@dataclass
class TelemetrySignal:
    session_id: str          # Anonymous session ID (unique per run)
    timestamp: float
    provider: str
    model: Optional[str]
    endpoint: str
    status_code: int
    latency_ms: int
    is_429: bool
    capabilities: List[str]
    fingerprint_unknown: bool

    def to_dict(self):
        return asdict(self)

class TelemetryCollector:
    def __init__(self, enabled: bool = False, cache_path: str = ".telemetry_cache.json"):
        self.enabled = enabled
        self.cache_path = cache_path
        self.session_id = str(uuid.uuid4())[:8]  # Short ID, not linkable to user
        self.buffer: List[TelemetrySignal] = self._load_cache()

    def _load_cache(self) -> List[TelemetrySignal]:
        if os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return [TelemetrySignal(**item) for item in data]
            except Exception:
                return []
        return []

    def _save_cache(self):
        if not self.enabled:
            return
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump([s.to_dict() for s in self.buffer], f, indent=2, ensure_ascii=False)
        except Exception:
            pass  # Silently fail, do not interrupt main flow

    def record(self, **kwargs):
        """Record a telemetry signal"""
        if not self.enabled:
            return

        sig = TelemetrySignal(session_id=self.session_id, timestamp=time.time(), **kwargs)
        self.buffer.append(sig)

        # Limit cache size (max 1000 entries)
        if len(self.buffer) > 1000:
            self.buffer = self.buffer[-1000:]

        self._save_cache()

    def export(self, out_path: str):
        """Export aggregated data (for CI use)"""
        data = [s.to_dict() for s in self.buffer]
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def clear(self):
        """Clear cache (on user request)"""
        self.buffer = []
        if os.path.exists(self.cache_path):
            try:
                os.remove(self.cache_path)
            except Exception:
                pass

    def get_summary(self) -> Dict:
        """Local statistics summary"""
        if not self.buffer:
            return {"total_signals": 0}

        total = len(self.buffer)
        count_429 = sum(1 for s in self.buffer if s.is_429)
        providers = {}
        for s in self.buffer:
            providers[s.provider] = providers.get(s.provider, 0) + 1

        return {
            "total_signals": total,
            "429_count": count_429,
            "429_rate": round(count_429 / total, 3),
            "providers": providers,
            "session_id": self.session_id,
        }

# ── Global singleton ──
_shared_telemetry = TelemetryCollector(enabled=False)

def get_telemetry() -> TelemetryCollector:
    return _shared_telemetry

def enable_telemetry(enable: bool = True, cache_path: str = None):
    """Global toggle (explicit user call)"""
    global _shared_telemetry
    _shared_telemetry.enabled = enable
    if cache_path:
        _shared_telemetry.cache_path = cache_path

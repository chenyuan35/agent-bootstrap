#!/usr/bin/env python3
"""
AI Self-Configuration Layer - Multi-key management / 429 switching / API failover / Model rotation / Rate limit protection

Design principles:
  1. AI reads environment variables directly, no human intervention
  2. Graceful degradation when unconfigured (demo mode)
  3. 30-second AI understandability
  4. No sensitive information exposure
"""
import os
import json
from typing import Dict, Any, List, Optional

# hive_collector removed - local stubs provide demo/degraded mode
_HAS_HIVE = False

# Stubs for compatibility (demo mode only)
class _KeyHive:
    def __init__(self, key_id, role):
        self.key_id = key_id
        self.role = role
        self.slots = []
    def add_slot(self, slot):
        self.slots.append(slot)

class _ModelSlot:
    def __init__(self, slot_id, endpoint, timeout=15.0, headers=None, payload_base=None):
        self.slot_id = slot_id
        self.endpoint = endpoint
        self.timeout = timeout
        self.headers = headers or {}
        self.payload_base = payload_base or {}
        self.fail_count = 0
        self.consecutive_429 = 0
        self.cooldown_until = 0.0
    def ready(self):
        import time
        return time.time() >= self.cooldown_until

class _HiveCollectorStub:
    def __init__(self, min_cooldown=5.0):
        self.min_cooldown = min_cooldown
        self.keys = []
    def collect(self, query, rounds=3, timeout=45.0, quorum=None):
        import json
        return json.dumps({
            "ok": False,
            "message": "demo mode - no external collector configured",
            "input_query": query,
            "material": "",
            "fragments": [],
            "quorum": "0/3"
        }, indent=2, ensure_ascii=False)


class AgentConfig:
    """AI self-configuration - zero human intervention"""

    def __init__(self, prefix: str = "HIVE_"):
        self.prefix = prefix
        self.mode = self._get_mode()          # live | demo
        self.key_count = self._detect_keys()

    # ── Mode Detection ──
    def _get_mode(self) -> str:
        """live=production, demo=demo (no keys configured)"""
        has_keys = any(k.startswith(self.prefix) for k in os.environ)
        return "live" if has_keys else "demo"

    # ── Key Detection ──
    def _detect_keys(self) -> int:
        """Auto-detect number of configured keys from environment"""
        count = 0
        for i in range(10):  # Support up to 10 keys
            ep_key = f"{self.prefix}{i}_ENDPOINT"
            if ep_key in os.environ or f"{self.prefix}{i}_URL" in os.environ:
                count += 1
        return count or self._count_from_string()

    def _count_from_string(self) -> int:
        """Parse multiple endpoints from single KEYS variable"""
        keys_str = os.environ.get(f"{self.prefix}KEYS", "")
        if not keys_str:
            return 0
        parts = [p.strip() for p in keys_str.split(",") if p.strip()]
        return len(parts)

    # ── Build Hive ──
    def make_hive(self, role_map: Optional[Dict[int, str]] = None) -> Any:
        """
        Auto-build HiveCollector, bind environment keys

        Args:
            role_map: {key_index: role_name}
                     default: 0,1,2=gather, 3=maintain, 4=output

        Returns:
            HiveCollector instance (or demo placeholder)
        """
        if not _HAS_HIVE:
            return self._demo_fallback("no external collector configured - running in demo mode")

        if self.mode == "demo":
            return self._demo_fallback("no keys configured")

        # Default role assignment
        if role_map is None:
            role_map = {0: "gather", 1: "gather", 2: "gather",
                       3: "maintain", 4: "output"}

        hc = _HiveCollectorStub(min_cooldown=5.0)
        hc.keys = []  # Clear default placeholders

        # Bind each key with 10 model slots
        for idx in range(self.key_count):
            role = role_map.get(idx, "gather")
            key_id = f"key_{idx}"
            endpoints = self._get_key_endpoints(idx)

            if not endpoints:
                continue

            kh = _KeyHive(key_id=key_id, role=role)
            for slot_idx, ep in enumerate(endpoints):
                slot = _ModelSlot(
                    slot_id=f"{key_id}_m{slot_idx}",
                    endpoint=ep,
                    timeout=float(os.environ.get(f"{self.prefix}{idx}_TIMEOUT", "15")),
                    headers=self._parse_headers(idx),
                    payload_base=self._parse_payload_base(idx),
                )
                kh.add_slot(slot)
            hc.keys.append(kh)

        # Fill remaining with demo placeholders (ensure 50 total slots)
        while len(hc.keys) < 5:  # Minimum 5 key placeholders
            fake_id = f"key_{len(hc.keys)}"
            role = role_map.get(len(hc.keys), "gather")
            kh = _KeyHive(key_id=fake_id, role=role)
            for m in range(10):
                kh.add_slot(_ModelSlot(
                    slot_id=f"{fake_id}_m{m}",
                    endpoint="https://demo.example.com/q",
                    timeout=15.0,
                ))
            hc.keys.append(kh)

        return hc

    def _get_key_endpoints(self, idx: int) -> List[str]:
        """Get all endpoints for a key (supports multi-model)"""
        # Method 1: Multiple individual variables
        eps = []
        for m in range(10):
            ep = os.environ.get(f"{self.prefix}{idx}_MODEL{m}") or \
                 os.environ.get(f"{self.prefix}{idx}_EP{m}")
            if ep:
                eps.append(ep)
        if eps:
            return eps

        # Method 2: Single URL variable + path suffix
        base = os.environ.get(f"{self.prefix}{idx}_ENDPOINT") or \
               os.environ.get(f"{self.prefix}{idx}_URL")
        if base:
            # If URL contains {model} placeholder, expand
            if "{model}" in base:
                return [base.format(model=i) for i in range(10)]
            # Otherwise 10 slots share same endpoint (model rotation)
            return [base] * 10

        # Method 3: Parse from KEYS string
        keys_str = os.environ.get(f"{self.prefix}KEYS", "")
        if keys_str:
            parts = [p.strip() for p in keys_str.split(",")]
            if idx < len(parts):
                ep = parts[idx]
                if "{model}" in ep:
                    return [ep.format(model=i) for i in range(10)]
                return [ep] * 10

        return []

    def _parse_headers(self, idx: int) -> Dict[str, str]:
        """Parse custom headers from environment"""
        raw = os.environ.get(f"{self.prefix}{idx}_HEADERS", "")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            pairs = [p.strip() for p in raw.split(";") if p.strip()]
            result = {}
            for p in pairs:
                if ":" in p:
                    k, v = p.split(":", 1)
                    result[k.strip()] = v.strip()
            return result

    def _parse_payload_base(self, idx: int) -> Dict[str, str]:
        """Parse base payload from environment"""
        raw = os.environ.get(f"{self.prefix}{idx}_PAYLOAD", "")
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except Exception:
            return {}

    # ── Demo Mode ──
    def _demo_fallback(self, reason: str) -> Any:
        """Return demo placeholder when unconfigured (AI can still call, returns example)"""
        class DemoHive:
            def __init__(self, r):
                self.reason = r
            def collect(self, query, rounds=3, timeout=45, **kw):
                import json
                return json.dumps({
                    "ok": False,
                    "message": f"demo mode: {self.reason}",
                    "hint": "Set HIVE_0_URL=... or HIVE_KEYS=url1,url2,...",
                    "input_query": query,
                    "material": "",
                    "fragments": [],
                    "quorum": "0/3",
                }, indent=2, ensure_ascii=False)
            async def collect_async(self, *a, **kw):
                import json
                return json.loads(self.collect(*a, **kw))
        return DemoHive(reason)

    # ── Quick Guide ──
    @staticmethod
    def help() -> str:
        """AI-readable 30-second guide"""
        return """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  HiveCollector · Multi-key management / 429 switching / API failover / Model rotation / Rate limit protection
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Environment Variable Configuration (choose one)

   Option A - Single key, single model (simplest):
     export HIVE_0_URL="https://api.xxx.com/query"

   Option B - Single key, multiple models (recommended):
     export HIVE_0_MODEL0="https://api.xxx.com/m0"
     export HIVE_0_MODEL1="https://api.xxx.com/m1"
     ...

   Option C - Multiple keys batch configuration:
     export HIVE_KEYS="url1,url2,url3,url4,url5"

   Option D - Full configuration (with headers):
     export HIVE_0_ENDPOINT="https://api.xxx.com/q"
     export HIVE_0_HEADERS='{"Authorization":"Bearer xxx"}'
     export HIVE_0_TIMEOUT=20

2. Code Call

   from agent_bootstrap.ai_config import AgentConfig
   # or (auto-read environment variables):
   from agent_bootstrap.ai_config import AgentConfig

   cfg = AgentConfig()
   hc = cfg.make_hive()      # auto-bind keys

   result = hc.collect(
       "human question",
       rounds=3,      # max rounds
       timeout=45,    # total timeout
       quorum=None,   # min success (None=auto half+1)
   )

3. Role Assignment (optional)

   cfg.make_hive(role_map={
       0: "gather",   # key0 = gather
       1: "gather",   # key1 = gather
       2: "gather",   # key2 = gather
       3: "maintain", # key3 = maintain
       4: "output",   # key4 = output
   })

4. Degraded Mode

   No keys configured -> auto demo mode,
   AI can still call but returns friendly prompt,
   does not affect debugging flow.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""


# ── Quick Functions ──
def auto_hive(role_map: Optional[Dict[int, str]] = None):
    """One-click create configured Hive"""
    return AgentConfig().make_hive(role_map)


if __name__ == "__main__":
    print(AgentConfig.help())

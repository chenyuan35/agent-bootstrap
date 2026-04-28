#!/usr/bin/env python3
"""ResilienceGuard - Unified resilience protection entry point

One key, simple loop:
    guard = ResilienceGuard(db_path="state.db")
    result = guard.execute("openai", lambda: (200, "ok", {}))
"""
import time
import threading
from typing import Callable, Dict, Any, Optional
from pathlib import Path

from .controller import ProviderController, State, Event
from .router import ProviderRouter
from .classifier import classify, FailureClass


class ResilienceGuard:
    """Lightweight resilience protector

    Design: One controller + router + persistence.
    No complex strategies, no research features, production-focused.
    """

    def __init__(self,
                 db_path: str = "provider_state.db",
                 mode: str = "conservative",
                 auto_save: bool = True):
        """
        Args:
            db_path: SQLite state file path ("" or None for no persistence)
            mode: conservative | adaptive
                  conservative = no automatic budget reduction, state tracking only
                  adaptive = enable adaptive budgeting
            auto_save: Auto-save state to DB after each event
        """
        self.db_path = db_path if db_path else None
        self.mode = mode
        self.auto_save = auto_save
        self.adaptive = (mode == "adaptive")
        self.enable_retry_after = True

        self._controllers_lock = threading.Lock()
        self._controllers: Dict[str, ProviderController] = {}
        self._router = ProviderRouter()

        # Load existing state
        if self.db_path:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

    # ---- Core API ----

    def execute(self,
                provider: str,
                request_fn: Callable[[], tuple[int, str, Dict[str, str]]],
                **kwargs) -> Dict[str, Any]:
        """
        Execute request with resilience protection

        Args:
            provider: Provider identifier
            request_fn: Returns (status_code, text, headers_dict)

        Returns:
            {
              "status": "ok" | "error" | "rejected",
              "code": int | None,
              "failure": str | None,
              "latency_ms": int,
              "provider": str,
              "state": str,
              "health": float,
              "rps_budget": float,
              "message": str | None,
            }
        """
        pc = self._get_controller(provider)

        # Check if request is allowed
        can_req, reason = pc.can_request()
        if not can_req:
            return {
                "status": "rejected",
                "code": None,
                "failure": None,
                "latency_ms": 0,
                "provider": provider,
                "state": pc.state.value,
                "health": pc.health,
                "rps_budget": pc.rps_budget,
                "message": reason,
            }

        # Execute request
        start = time.time()
        try:
            status_code, text, headers = request_fn()
            latency = int((time.time() - start) * 1000)
        except Exception as e:
            latency = int((time.time() - start) * 1000)
            return self._handle_exception(pc, str(e), latency)

        # Process response
        return self._handle_response(pc, status_code, text, headers, latency)

    def route(self,
              providers: list,
              request_fn=None) -> Dict[str, Any]:
        """
        Auto-select best provider and execute

        Args:
            providers: Available provider list
            request_fn: Optional, if provided will execute

        Returns:
            Selected provider and result
        """
        for p in providers:
            self._get_controller(p)

        selected = self._router.select(self._controllers)

        if not selected:
            return {
                "status": "rejected",
                "message": "no available provider",
                "ranking": self.rank(providers),
            }

        result = {
            "status": "selected",
            "provider": selected,
            "score": self._router._score_provider(self._controllers[selected], selected),
            "ranking": self.rank(providers),
        }

        if request_fn:
            exec_result = self.execute(selected, request_fn)
            result["execution"] = exec_result

        return result

    def health(self) -> Dict[str, Any]:
        """All provider health snapshot"""
        return {
            name: pc.snapshot()
            for name, pc in self._controllers.items()
        }

    def rank(self, providers: Optional[list] = None) -> list:
        """Provider ranking (debug)"""
        targets = {}
        for p in (providers or list(self._controllers.keys())):
            if p in self._controllers:
                targets[p] = self._controllers[p]
        return self._router.rank(targets)

    def reset(self, provider: Optional[str] = None, hard: bool = False):
        """Reset state"""
        with self._controllers_lock:
            if provider:
                if provider in self._controllers:
                    if hard:
                        del self._controllers[provider]
                    else:
                        pc = self._controllers[provider]
                        pc.state = State.HEALTHY
                        pc.health = 100.0
                        pc.rps_budget = 10.0
                        pc.failure_count = 0
                        pc.cooldown_until = 0.0
                        if self.db_path:
                            pc.save(self.db_path)
            else:
                self._controllers.clear()

    # ---- Internal ----

    def _get_controller(self, provider: str) -> ProviderController:
        with self._controllers_lock:
            if provider not in self._controllers:
                if self.db_path:
                    pc = ProviderController.load(
                        name=provider,
                        db_path=self.db_path,
                        max_rps=100.0,
                        min_rps=1.0,
                    )
                else:
                    pc = ProviderController(
                        name=provider,
                        max_rps=100.0,
                        min_rps=1.0,
                        db_path=self.db_path,
                    )
                self._controllers[provider] = pc
                self._router.register_provider(provider)
            return self._controllers[provider]

    def _handle_response(self,
                         pc: ProviderController,
                         status_code: int,
                         text: str,
                         headers: Dict[str, str],
                         latency: int) -> Dict[str, Any]:
        """Process response"""
        self._router.record_latency(pc.name, latency)

        # Parse Retry-After
        retry_after = None
        if self.enable_retry_after:
            retry_after = self._parse_retry_after(headers)

        if 200 <= status_code < 300:
            pc.transition(Event.SUCCESS, retry_after=retry_after)
            event = Event.SUCCESS
            result_status = "ok"
            failure = None
        else:
            failure = classify(status_code, region=None, text=text)
            event = self._failure_to_event(failure)
            pc.transition(event, retry_after=retry_after)
            result_status = "error"

        if self.auto_save and self.db_path:
            pc.save(self.db_path)

        return {
            "status": result_status,
            "code": status_code,
            "failure": failure.value if failure else None,
            "latency_ms": latency,
            "provider": pc.name,
            "state": pc.state.value,
            "health": pc.health,
            "rps_budget": pc.rps_budget,
            "message": f"{failure.value if failure else 'ok'} (h={pc.health:.0f})",
        }

    def _handle_exception(self,
                          pc: ProviderController,
                          error_msg: str,
                          latency: int) -> Dict[str, Any]:
        """Process exception"""
        pc.transition(Event.TIMEOUT, retry_after=None)

        if self.auto_save and self.db_path:
            pc.save(self.db_path)

        return {
            "status": "error",
            "code": None,
            "failure": Event.TIMEOUT.value,
            "latency_ms": latency,
            "provider": pc.name,
            "state": pc.state.value,
            "health": pc.health,
            "rps_budget": pc.rps_budget,
            "message": error_msg[:50],
        }

    def _parse_retry_after(self, headers: Dict[str, str]) -> Optional[float]:
        """Parse Retry-After header (seconds or HTTP date)"""
        if not headers:
            return None
        val = headers.get("Retry-After") or headers.get("retry-after")
        if not val:
            return None
        val = val.strip()
        if not val:
            return None
        # Seconds
        try:
            return float(val)
        except ValueError:
            pass
        # HTTP date
        from datetime import datetime
        for fmt in ("%a, %d %b %Y %H:%M:%S GMT", "%a, %d-%b-%Y %H:%M:%S GMT"):
            try:
                return datetime.strptime(val, fmt).timestamp() - time.time()
            except ValueError:
                pass
        return None

    def _failure_to_event(self, failure: FailureClass) -> Event:
        """Failure class -> event"""
        mapping = {
            FailureClass.RATE_LIMIT: Event.RATE_LIMIT,
            FailureClass.REGIONAL_LIMIT: Event.RATE_LIMIT,
            FailureClass.CAPACITY: Event.CAPACITY,
            FailureClass.AUTH_FAILURE: Event.AUTH_FAILURE,
            FailureClass.PERMISSION_DENIED: Event.AUTH_FAILURE,
            FailureClass.TRANSIENT: Event.TIMEOUT,
            FailureClass.UNKNOWN: Event.TIMEOUT,
        }
        return mapping.get(failure, Event.TIMEOUT)

    def _adjust_budget(self,
                       pc: ProviderController,
                       failure: FailureClass,
                       status_code: int):
        """Adaptive budget adjustment (deprecated: moved to controller)"""
        pass

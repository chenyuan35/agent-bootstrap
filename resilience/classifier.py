#!/usr/bin/env python3
"""Failure classifier: Maps HTTP/status/text to semantic failure categories"""
from enum import Enum
from typing import Dict


class FailureClass(Enum):
    RATE_LIMIT = "rate_limit"
    REGIONAL_LIMIT = "regional_limit"
    CAPACITY = "capacity"
    AUTH_FAILURE = "auth_failure"
    PERMISSION_DENIED = "permission_denied"
    TRANSIENT = "transient"
    UNKNOWN = "unknown"


STATUS_MAP: Dict[int, FailureClass] = {
    429: FailureClass.RATE_LIMIT,
    529: FailureClass.RATE_LIMIT,   # Cloudflare overload
    503: FailureClass.CAPACITY,
    502: FailureClass.CAPACITY,
    504: FailureClass.CAPACITY,
    401: FailureClass.AUTH_FAILURE,
    403: FailureClass.PERMISSION_DENIED,
}


def classify(status_code: int, region: str = None, text: str = "") -> FailureClass:
    """Classify response into failure category"""
    if status_code == 403 and "rate limit" in text.lower():
        return FailureClass.REGIONAL_LIMIT
    return STATUS_MAP.get(status_code, FailureClass.UNKNOWN)

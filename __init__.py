"""Agent Bootstrap - Autonomous AI Infrastructure

Let AI manage API keys, learn configuration, and optimize routing by itself.
"""

__version__ = "2.1.119"

# ── Telemetry ──
from agent_bootstrap.telemetry import get_telemetry, enable_telemetry, TelemetryCollector

# ── Key Format (Authorized credential format recognition) ──
from agent_bootstrap.key_format.catalog import (
    identify_by_prefix,
    get_format_by_provider_name,
    get_formats_by_family,
    provider_families,
)

# ── Resilience ──
from agent_bootstrap.resilience.classifier import FailureClass, classify
from agent_bootstrap.resilience.guard import ResilienceGuard

# ── Retrieval Middleware ──
# ── Hive Collector ──
# Removed: hive_collector module is now standalone in AI-assistant-tools/ directory
from agent_bootstrap.retrieval_middleware import retrieval_middleware
# ── AI Self-Configuration Layer ──
from agent_bootstrap.ai_config import AgentConfig, auto_hive
# ── Orchestrator (compatibility alias) ──
from agent_bootstrap.resilience.guard import ResilienceGuard as BootstrapOrchestrator

__all__ = [
    "__version__",
    # Telemetry
    "get_telemetry", "enable_telemetry", "TelemetryCollector",
    # Key Format
    "identify_by_prefix", "get_format_by_provider_name", "get_formats_by_family", "provider_families",
    # Resilience
    "FailureClass", "classify", "ResilienceGuard",
    # Hive Collector (multi-key management / 429 switching / API failover / model rotation / rate limit protection)
    # Removed: hive_collector is now standalone in AI-assistant-tools/ directory
    # AI Config
    "AgentConfig", "auto_hive",
    # Retrieval Middleware
    "retrieval_middleware",
    # Orchestrator
    "BootstrapOrchestrator",
]

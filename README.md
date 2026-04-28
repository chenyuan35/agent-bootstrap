# AgentBootstrap

Autonomous AI Infrastructure for self-configured API routing, circuit breaking, and resilience.

AgentBootstrap provides single-key resilience (retry, circuit breaker, rate limit guard) and an AI self-configuration layer that auto-binds API keys and endpoints from environment variables.

## ⚠️ Disclaimer

**Authorized use only:**

- ✅ **Permitted**: Personal code sanitization, AI-generated content sensitive info detection, security self-checks.
- ✅ **Scope**: General development API keys only (AI models, cloud services, databases, open-source service keys).
- ❌ **Prohibited**: Illegal scanning, unauthorized collection of others' sensitive data, bulk public network scanning.
- ❌ **Excluded**: Financial/payment keys and social account credentials are **deliberately removed** — this project contains **zero** such rules.

This project is a **key format recognition tool** (pattern matching only, no network calls, no key validation).

## Quick start

```python
from agent_bootstrap import ResilienceGuard

# Single-key resilient execution
guard = ResilienceGuard(
    max_retries=3,
    circuit_breaker_threshold=5,
    rate_limit_guard=True
)

result = guard.execute(
    task="Summarize the latest market report",
    model="claude-3-5-sonnet-20241022"
)
```

## AI self-configuration

`AgentConfig` auto-detects configured keys from environment variables and builds a multi-key collector interface (safe to call; degrades gracefully when unconfigured).

```python
from agent_bootstrap.ai_config import AgentConfig

cfg = AgentConfig()
hc = cfg.make_hive()
```

Environment variables (examples):

- `HIVE_0_URL=https://api.example.com/query`
- `HIVE_KEYS=url1,url2,url3,url4,url5`
- `HIVE_0_HEADERS='{"Authorization":"Bearer xxx"}'`
- `HIVE_0_TIMEOUT=20`

See `ai_config.py` for details.

## Features

- **ResilienceGuard**: circuit breaker, retry, rate-limit guard (single-key)
- **AIConfig**: zero-intervention environment-based key/endpoint binding
- **KeyFormat catalog**: authorized credential format recognition utilities
- **Telemetry**: opt-in session telemetry collection
- **RetrievalMiddleware**: request/response post-processing hooks

## Installation / development

```bash
pip install -e .
```

## Running tests

```bash
pytest
```

## License

See LICENSE file.

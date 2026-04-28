#!/usr/bin/env python3
"""
RetrievalMiddleware - Stateless AI retrieval tool (single use)

Concise design:
  - 200 lines core, no unnecessary abstractions
  - Tiered fallback: rate_limit[5,30,120] / capacity[10,60,300]
  - Min cooldown=5s protects free-tier keys
  - Local decay: success only reduces its own node fail_count
  - Debug info only when debug=True

Usage:
    result = retrieval_middleware(query, timeout=45, quorum=None, max_rounds=3)
"""
import asyncio, json, re, time
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional

try:
    import httpx
    _HAS_HTTPX = True
except Exception:
    _HAS_HTTPX = False

try:
    from bs4 import BeautifulSoup
    _HAS_BS4 = True
except Exception:
    _HAS_BS4 = False


# ── Lightweight Route Unit ──
@dataclass
class RouteUnit:
    name: str
    url: str
    method: str = "get"
    headers: Dict[str, str] = field(default_factory=dict)
    payload: Optional[Dict] = None
    timeout: float = 15.0

    fail_count: int = 0
    cooldown_until: float = 0.0

    def ready(self) -> bool:
        return time.time() >= self.cooldown_until

    def record_success(self):
        self.fail_count = max(0, self.fail_count - 1)  # local decay

    def record_failure(self, fail_type: str, min_cooldown: float):
        self.fail_count += 1
        # Tiered backoff: rate < capacity < auth
        tables = {
            "rate_limit":  [5, 30, 120],
            "capacity":    [10, 60, 300],
            "auth_failure": [300, 600, 900],
            "other":       [5, 30, 120],
        }
        backs = tables.get(fail_type, tables["other"])
        backoff = backs[min(self.fail_count - 1, 2)]
        cooldown = max(backoff, min_cooldown)
        self.cooldown_until = time.time() + cooldown


# ── Text Processing ──
def _strip_html(raw: str) -> str:
    if not raw or not isinstance(raw, str):
        return ""
    if _HAS_BS4:
        try:
            return BeautifulSoup(raw, "html.parser").get_text(separator=" ", strip=True)
        except Exception:
            pass
    return re.sub(r'\s+', " ", re.sub(r'<[^>]+>', " ", raw)).strip()


def _truncate(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    chunk = text[:limit]
    for sep in ("。", "？", "！", ".", "!", "?"):
        pos = chunk.rfind(sep)
        if pos > 0:
            return chunk[:pos + len(sep)].strip()
    pos = chunk.rfind(" ")
    return chunk[:pos].strip() if pos > 0 else chunk


def _is_valid(text: str) -> bool:
    if not text or len(text) < 30:
        return False
    printable = sum(1 for c in text if c.isprintable() and not c.isspace())
    return (printable / max(1, len(text))) >= 0.3


def _classify(status_code: int) -> str:
    if status_code in (429, 529):
        return "rate_limit"
    if status_code in (503, 502, 504):
        return "capacity"
    if status_code in (401, 403):
        return "auth_failure"
    return "other"


def _parse_retry_after(headers: Dict) -> Optional[float]:
    val = (headers or {}).get("Retry-After") or (headers or {}).get("retry-after")
    if not val:
        return None
    try:
        return float(str(val).strip())
    except ValueError:
        return None


# ── Single Route Fetch ──
async def _fetch_one(route: RouteUnit, client, payload: Dict, queue, stop, min_cooldown: float):
    while not stop.is_set():
        if not route.ready():
            await asyncio.sleep(0.5)
            continue
        try:
            if route.method.lower() == "get":
                resp = await client.get(route.url, headers=route.headers, timeout=route.timeout)
            else:
                resp = await client.post(route.url, json=route.payload or payload,
                                        headers=route.headers, timeout=route.timeout)
            text = getattr(resp, "text", "")
            status = getattr(resp, "status_code", 200)
            retry_after = _parse_retry_after(getattr(resp, "headers", {}))

            if 200 <= status < 300:
                cleaned = _strip_html(text)
                if _is_valid(cleaned):
                    route.record_success()
                    await queue.put({"source": route.name, "status": "ok",
                                   "text": _truncate(cleaned, 2000), "len": len(cleaned)})
                    stop.set()
                    return
                route.record_failure("other", min_cooldown)
            else:
                route.record_failure(_classify(status), min_cooldown)
            await queue.put({"source": route.name, "status": _classify(status), "len": len(text)})
            return
        except asyncio.CancelledError:
            return
        except Exception:
            route.record_failure("other", min_cooldown)
            await queue.put({"source": route.name, "status": "error", "len": 0})
            return
        await asyncio.sleep(0.1)


# ── Core Retrieval ──
async def _retrieve_async(routes: List[Dict[str, Any]], timeout: float,
                         quorum: Optional[int], max_rounds: int, min_cooldown: float) -> Dict[str, Any]:
    if not _HAS_HTTPX:
        return {"ok": False, "message": "httpx not installed", "fragments": []}

    route_objs = [RouteUnit(name=r.get("name", f"r{i}"), url=r["url"],
                            method=r.get("method", "get"), headers=r.get("headers", {}),
                            payload=r.get("payload"), timeout=r.get("timeout", 15.0))
                  for i, r in enumerate(routes)]

    if not route_objs:
        return {"ok": False, "message": "no routes configured", "fragments": [], "quorum": "0/0"}

    total = len(route_objs)
    q = quorum or (total // 2 + 1)
    deadline = time.time() + timeout
    results: List[Dict[str, Any]] = []
    queue: asyncio.Queue = asyncio.Queue()

    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=10), timeout=30.0) as client:
        for _ in range(max_rounds):
            if time.time() >= deadline or len(results) >= q:
                break
            ready = [r for r in route_objs if r.ready()]
            if not ready:
                cooling = [r for r in route_objs if not r.ready()]
                if not cooling:
                    break
                wait = max(0.1, min(r.cooldown_until for r in cooling) - time.time())
                wait = min(wait, deadline - time.time())
                if wait > 0:
                    await asyncio.sleep(wait)
                continue

            stop = asyncio.Event()
            tasks = [asyncio.create_task(_fetch_one(r, client, {}, queue, stop, min_cooldown))
                    for r in ready]
            try:
                await asyncio.wait(tasks, timeout=15.0, return_when=asyncio.FIRST_COMPLETED)
            except asyncio.CancelledError:
                pass

            while not queue.empty():
                try:
                    out = queue.get_nowait()
                    if out not in results:
                        results.append(out)
                except asyncio.QueueEmpty:
                    break

            for t in tasks:
                if not t.done():
                    t.cancel()
            stop.clear()

    ok_res = [r for r in results if r["status"] == "ok"]
    if len(ok_res) >= q:
        combined = "\n\n".join(r["text"] for r in ok_res)
        return {"ok": True, "material": _truncate(combined, 3000),
                "fragments": [{"source": r["source"], "text": r["text"]} for r in ok_res],
                "quorum": f"{len(ok_res)}/{q}"}
    if ok_res:
        return {"ok": False, "material": "",
                "fragments": [{"source": r["source"], "text": r.get("text", "")} for r in ok_res],
                "quorum": f"{len(ok_res)}/{q}", "message": "insufficient responses"}
    return {"ok": False, "material": "", "fragments": [],
            "quorum": f"0/{q}", "message": "all routes failed"}


def retrieval_middleware(query: str, timeout: float = 45.0,
                        quorum: Optional[int] = None, max_rounds: int = 3,
                        min_cooldown: float = 5.0, debug: bool = False) -> str:
    """Retrieval middleware entry point"""
    from agent_bootstrap.retrieval_middleware import ROUTE_TABLE
    routes = [{"name": k, "url": v, "method": "get"} for k, v in ROUTE_TABLE.items()]
    result = asyncio.run(_retrieve_async(routes, timeout, quorum, max_rounds, min_cooldown))
    result["input_query"] = query
    if debug:
        result["_debug_nodes"] = {r["name"]: {"fail_count": r.fail_count,
                                            "cooldown_until": r.cooldown_until,
                                            "ready": r.ready()}
                                for r in [RouteUnit(name=k, url=v) for k, v in ROUTE_TABLE.items()]}
    return json.dumps(result, indent=2, ensure_ascii=False)


# ── Default Routes ──
ROUTE_TABLE: Dict[str, str] = {
    "route_0": "https://api.node-0.example/query",
    "route_1": "https://api.node-1.example/query",
    "route_2": "https://api.node-2.example/query",
    "route_3": "https://api.node-3.example/query",
    "route_4": "https://api.node-4.example/query",
}

#!/usr/bin/env python3
"""
Smart Cost Router - Automatic cost-based routing

Automatically selects cheapest model while maintaining task quality.
"""

from agent_bootstrap import ResilienceGuard
import time


# Model pricing (per 1K tokens, USD)
MODEL_COST = {
    "gpt-3.5-turbo":    {"input": 0.0005, "output": 0.0015},
    "gpt-4":            {"input": 0.030,  "output": 0.12},
    "gpt-4-turbo":      {"input": 0.010,  "output": 0.03},
    "claude-3-haiku":   {"input": 0.00025, "output": 0.00125},
    "claude-3-opus":    {"input": 0.015,  "output": 0.075},
    "claude-3-sonnet":  {"input": 0.003,  "output": 0.015},
    "gemini-pro":       {"input": 0.0005, "output": 0.0015},
    "gemini-1.5-pro":   {"input": 0.0035, "output": 0.0105},
}

# Provider capability mapping: provider -> {capability -> model_name}
PROVIDER_MODELS = {
    "openai":       {"cheap": "gpt-3.5-turbo",   "mid": "gpt-4",         "strong": "gpt-4-turbo"},
    "anthropic":    {"cheap": "claude-3-haiku",  "mid": "claude-3-sonnet","strong": "claude-3-opus"},
    "gemini":       {"cheap": "gemini-pro",      "mid": "gemini-1.5-pro","strong": "gemini-1.5-pro"},
    "deepseek":     {"cheap": "deepseek-chat",   "mid": "deepseek-coder", "strong": "deepseek-coder"},
}

# Provider cost factor (lower = cheaper)
PROVIDER_COST_FACTOR = {
    "deepseek": 0.3,
    "gemini":   0.6,
    "openai":   1.0,
    "anthropic":0.9,
}

# Task complexity heuristic rules
def estimate_complexity(prompt: str) -> str:
    """
    Estimate task complexity: cheap | mid | strong
    """
    prompt_lower = prompt.lower()

    simple_keywords = ["hello", "hi", "help", "explain", "summary", "list", "what is"]
    complex_keywords = ["code", "write", "implement", "fix", "debug", "refactor",
                        "optimize", "algorithm", "class", "function", "api",
                        "sql", "python", "javascript", "react", "typescript"]
    heavy_keywords = ["architecture", "design", "system", "scalab", "distribut",
                      "microservice", "deployment", "kubernetes", "docker",
                      "review", "analyze", "full", "complete", "entire"]

    score = 0
    words = prompt_lower.split()
    word_count = len(words)

    # 
    if word_count > 500:
        score += 2
    elif word_count > 200:
        score += 1

    # 
    for kw in heavy_keywords:
        if kw in prompt_lower:
            score += 3
    for kw in complex_keywords:
        if kw in prompt_lower:
            score += 2
    for kw in simple_keywords:
        if kw in prompt_lower:
            score -= 1

    if score >= 4:
        return "strong"
    elif score >= 2:
        return "mid"
    else:
        return "cheap"


def estimate_cost(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate single-call cost (USD)"""
    if model not in MODEL_COST:
        return 0.0
    m = MODEL_COST[model]
    return (m["input"] * prompt_tokens / 1000) + (m["output"] * completion_tokens / 1000)


def smart_route(guard: ResilienceGuard,
                prompt: str,
                mode: str = "balanced",
                providers: list = None) -> dict:
    """
    Smart cost routing

    Args:
        guard: ResilienceGuard instance
        prompt: User prompt
        mode: balanced | economy | premium
            - economy: cheapest, pick lowest-cost capable model
            - balanced: best price-performance
            - premium: best quality, cost no object
        providers: Optional provider list

    Returns:
        {
            "provider": str,
            "model": str,
            "capability": str,
            "estimated_cost_usd": float,
            "rationale": str,
            "alternatives": list
        }
    """
    if providers is None:
        providers = ["openai", "anthropic", "gemini", "deepseek"]

    #  provider 
    for p in providers:
        guard._get_controller(p)

    # 
    complexity = estimate_complexity(prompt)

    #  mode  
    if mode == "economy":
        # Economy mode: prefer cheap over mid
        target_capability = complexity
    elif mode == "premium":
        # Premium mode: use strong directly
        target_capability = "strong"
    else:
        # Balanced mode: elastic selection by complexity
        target_capability = complexity

    # 
    candidates = []
    for provider in providers:
        models = PROVIDER_MODELS.get(provider, {})
        if target_capability in models:
            model_name = models[target_capability]
            cost_factor = PROVIDER_COST_FACTOR.get(provider, 1.0)

            # Check provider health status
            pc = guard._controllers.get(provider)
            if pc:
                can_req, reason = pc.can_request()
                health = pc.health
                state = pc.state.value
            else:
                can_req, reason = True, ""
                health = 100.0
                state = "healthy"

            # Base cost estimate (assume 1K tokens)
            base_cost = estimate_cost(provider, model_name, 500, 500)
            adjusted_cost = base_cost * cost_factor

            # Health penalty
            health_penalty = (100 - health) / 100 * adjusted_cost * 0.5

            total_cost = adjusted_cost + health_penalty

            # Score: lower cost = higher score, higher health = higher score
            if can_req and state != "quarantined":
                score = (1.0 / (total_cost + 0.001)) * (health / 100.0)
            else:
                score = -1.0

            # Savings vs strong mode
            strong_model = models.get("strong", model_name)
            strong_cost = estimate_cost(provider, strong_model, 500, 500) * cost_factor
            savings = max(0, strong_cost - total_cost)
            savings_pct = (savings / strong_cost * 100) if strong_cost > 0 else 0

            candidates.append({
                "provider": provider,
                "model": model_name,
                "capability": target_capability,
                "score": round(score, 4),
                "estimated_cost_usd": round(total_cost, 6),
                "savings_vs_premium_usd": round(savings, 6),
                "savings_pct": round(savings_pct, 1),
                "health": round(health, 1),
                "state": state,
                "can_request": can_req,
                "reason": reason,
            })

    # 
    candidates.sort(key=lambda x: x["score"], reverse=True)

    # 
    available = [c for c in candidates if c["score"] > 0]

    if not available:
        # All unavailable, pick first
        best = candidates[0] if candidates else {
            "provider": providers[0],
            "model": "unknown",
            "capability": target_capability,
            "score": 0,
            "estimated_cost_usd": 0,
            "savings_vs_premium_usd": 0,
            "savings_pct": 0,
            "health": 0,
            "state": "unknown",
            "can_request": False,
            "reason": "all providers unavailable",
        }
    else:
        best = available[0]

    # 
    rationales = {
        "economy": f" : {best['provider']}.{best['model']} ,  premium  ${best['savings_vs_premium_usd']:.4f} ({best['savings_pct']}%)",
        "balanced": f"  : {best['provider']}.{best['model']}  ( {best['health']})",
        "premium": f" : {best['provider']}.{best['model']} ",
    }
    rationale = rationales.get(mode, rationales["balanced"])

    if not best["can_request"]:
        rationale += f"  ({best['reason']})"

    return {
        "provider": best["provider"],
        "model": best["model"],
        "capability": best["capability"],
        "estimated_cost_usd": best["estimated_cost_usd"],
        "savings_vs_premium_usd": best["savings_vs_premium_usd"],
        "savings_pct": best["savings_pct"],
        "score": best["score"],
        "rationale": rationale,
        "alternatives": candidates[:3],
    }


class SmartCostGuard:
    """
     Guard 

    :
        guard = SmartCostGuard(db_path=None, mode="economy")
        result = guard.call_llm(
            prompt="",
            task="code",
            fallback=True
        )
    """

    def __init__(self,
                 db_path: str = None,
                 mode: str = "balanced",
                 auto_save: bool = True):
        """
        :
            db_path: SQLite 
            mode: balanced | economy | premium
            auto_save: 
        """
        self.guard = ResilienceGuard(
            db_path=db_path,
            mode="adaptive",
            auto_save=auto_save,
        )
        self.mode = mode
        self.total_savings = 0.0

    def call_llm(self,
                 prompt: str,
                 task: str = "chat",
                 fallback: bool = True,
                 providers: list = None,
                 max_retries: int = 3) -> dict:
        """
         LLM  ( OpenAI SDK)

        :
            prompt: 
            task: chat | code | cheap
            fallback: 
            providers:  provider 
            max_retries: 

        :
            {
              "status": "ok" | "error",
              "provider": str,
              "model": str,
              "response": str,
              "cost_usd": float,
              "savings_usd": float,
              "rationale": str,
            }
        """
        # 
        mode_map = {
            "chat": "balanced",
            "code": "premium",
            "cheap": "economy",
        }
        effective_mode = mode_map.get(task, self.mode)

        # 
        route_result = smart_route(
            self.guard,
            prompt,
            mode=effective_mode,
            providers=providers,
        )

        selected = route_result["provider"]
        rationale = route_result["rationale"]

        print(f"\n{rationale}")

        # 
        if fallback:
            #  failover 
            providers_ordered = [selected] + [p for p in (providers or ["openai", "anthropic", "gemini"]) if p != selected]

            for attempt in range(max_retries):
                result = self.guard.failover_execute(
                    providers=providers_ordered,
                    request_fn=lambda p=selected: self._make_request(p, prompt),
                )

                if result["status"] == "ok":
                    cost = route_result["estimated_cost_usd"]
                    savings = route_result["savings_vs_premium_usd"]
                    self.total_savings += savings

                    return {
                        "status": "ok",
                        "provider": result["provider"],
                        "model": route_result["model"],
                        "response": f"Response from {result['provider']} (attempt {result['attempt_count']})",
                        "cost_usd": round(cost, 6),
                        "savings_usd": round(savings, 6),
                        "rationale": rationale,
                    }

                if attempt < max_retries - 1:
                    print(f"    ... ({attempt + 1}/{max_retries})")

            return {
                "status": "error",
                "provider": None,
                "model": route_result["model"],
                "response": "All retries exhausted",
                "cost_usd": 0,
                "savings_usd": 0,
                "rationale": rationale,
            }
        else:
            # 
            result = self.guard.execute(
                selected,
                lambda: self._make_request(selected, prompt),
            )

            if result["status"] == "ok":
                cost = route_result["estimated_cost_usd"]
                savings = route_result["savings_vs_premium_usd"]
                return {
                    "status": "ok",
                    "provider": selected,
                    "model": route_result["model"],
                    "response": result.get("message", "ok"),
                    "cost_usd": round(cost, 6),
                    "savings_usd": round(savings, 6),
                    "rationale": rationale,
                }

            return {
                "status": "error",
                "provider": selected,
                "model": route_result["model"],
                "response": result.get("message", "error"),
                "cost_usd": route_result["estimated_cost_usd"],
                "savings_usd": 0,
                "rationale": rationale,
            }

    def _make_request(self, provider: str, prompt: str, status_code: int = 200):
        """ - """
        #  lambda  provider
        return status_code, f"Response from {provider}", {}

    def get_savings(self) -> float:
        """"""
        return round(self.total_savings, 6)


if __name__ == "__main__":
    print("\n=== Smart Cost Router Demo ===\n")

    guard = SmartCostGuard(db_path=None, mode="economy")

    # 
    print("1.  ()")
    r = guard.call_llm("Hello, how are you?", task="chat", fallback=False)
    print(f"    {r['rationale']}")

    # 
    print("\n2.  ()")
    r = guard.call_llm("Write a quicksort in Python", task="code", fallback=False)
    print(f"    {r['rationale']}")

    # 
    print("\n3. ")
    r = guard.call_llm("Summarize this text", task="cheap", fallback=False)
    print(f"    {r['rationale']}")

    print(f"\n : ${guard.get_savings():.4f}")

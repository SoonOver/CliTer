"""Strategy engine — model selection, fallback, round-robin, cheapest."""
import json
import time
import random
from cliter.proxy import manager as pm
from cliter.proxy import tracker
from cliter.config import settings
from cliter.utils.log import get_logger

log = get_logger("strategy")

# Strategy types
MANUAL = "manual"
FALLBACK = "fallback"
ROUND_ROBIN = "round_robin"
CHEAPEST = "cheapest"
AUTO = "auto"

# Model complexity keywords — simple = cheap model ok
_SIMPLE_KEYWORDS = ["hi", "hello", "ok", "yes", "no", "thanks", "summarize",
                    "translate", "short", "simple", "quick"]


async def get_active_strategy() -> str:
    """Get current strategy name from settings."""
    return settings.get("strategy", "mode", default=AUTO)


async def select_model(strategy: str, user_input: str = "",
                       available_connections: list[dict] = None,
                       preferred_model: str = "") -> dict:
    """Select the best model + connection based on strategy.
    
    Returns: {
        "provider": dict,
        "connection_id": str,
        "model": str,       # the upstream model name
        "display_model": str,  # the user-facing model name (with prefix)
        "strategy": str,
    }
    """
    if available_connections is None:
        available_connections = await _get_all_connections()
    
    if not available_connections:
        # Fallback: just use default provider
        providers = await pm.list_providers()
        if not providers:
            return {"error": "No providers configured"}
        # Use first active provider, first connection
        for p in providers:
            if p["is_active"]:
                return {
                    "provider": p,
                    "connection_id": p.get("id", ""),
                    "model": preferred_model or settings.get("llm", "model", default="gpt-4o-mini"),
                    "display_model": f"{p['prefix']}/{preferred_model}" if preferred_model else p['prefix'],
                    "strategy": "fallback",
                }
        return {"error": "No active providers"}
    
    # Filter out rate-limited connections
    active = []
    for conn in available_connections:
        if not isinstance(conn, dict):
            continue
        if not await tracker.is_rate_limited(conn.get("connection_id", "")):
            active.append(conn)
    
    if not active:
        log.warning("All connections rate-limited, picking first to retry")
        active = available_connections  # force retry
    
    if strategy == MANUAL or (strategy == MANUAL and preferred_model):
        return _manual_select(active, preferred_model)
    elif strategy == FALLBACK:
        return _fallback_select(active)
    elif strategy == ROUND_ROBIN:
        return await _round_robin_select(active)
    elif strategy == CHEAPEST:
        return _cheapest_select(active)
    elif strategy == AUTO:
        return await _auto_select(active, user_input, preferred_model)
    else:
        return _fallback_select(active)


async def _get_all_connections() -> list[dict]:
    """Get all available provider+connection combos."""
    providers = await pm.list_providers()
    result = []
    for p in providers:
        if not p["is_active"]:
            continue
        # Each provider = 1 connection (for now, extendable)
        result.append({
            "provider": p,
            "connection_id": p.get("id", ""),
            "provider_id": p.get("id", ""),
            "prefix": p.get("prefix", ""),
            "models": json.loads(p.get("models", "[]")),
            "priority": p.get("priority", 0),
            "api_key": p.get("api_key", ""),
            "base_url": p.get("base_url", ""),
        })
    return result


def _manual_select(connections: list[dict], preferred: str) -> dict:
    """Manual: try to match preferred model, else first available."""
    if preferred:
        # Check if preferred is a virtual unified model
        if preferred in VIRTUAL_MODELS:
            # Pick first connection and resolve virtual model mapping
            for conn in connections:
                prefix = conn["prefix"]
                if prefix in VIRTUAL_MODELS[preferred]:
                    target_model = VIRTUAL_MODELS[preferred][prefix]
                    return _make_result(conn, target_model)
            # Fallback
            conn = connections[0]
            models = conn["models"]
            return _make_result(conn, models[0] if models else "")

        # If preferred already has prefix format, strip it
        stripped_model = preferred
        if "/" in preferred:
            prefix_guess = preferred.split("/", 1)[0]
            stripped_model = preferred.split("/", 1)[1]
            # Try exact prefix match
            for conn in connections:
                if conn["prefix"] == prefix_guess:
                    return _make_result(conn, stripped_model)
        # Try exact model match
        for conn in connections:
            if preferred in conn["models"] or preferred == conn["prefix"]:
                return _make_result(conn, stripped_model if "/" in preferred else preferred)
        # Fallback: pick any
        if connections:
            return _make_result(connections[0], stripped_model if "/" in preferred else preferred)
    if connections:
        return _make_result(connections[0], connections[0]["models"][0] if connections[0]["models"] else "")
    return {"error": "No connections"}


def _fallback_select(connections: list[dict]) -> dict:
    """Fallback: return highest priority non-rate-limited."""
    sorted_conns = sorted(connections, key=lambda c: -c["priority"])
    for conn in sorted_conns:
        models = conn["models"]
        if models:
            return _make_result(conn, models[0])
    if sorted_conns:
        return _make_result(sorted_conns[0], "")
    return {"error": "No connections"}


async def _round_robin_select(connections: list[dict]) -> dict:
    """Round-robin across connections."""
    # Get last used index from settings
    idx_key = "_rr_index"
    rr_index = int(await pm.get_config(idx_key, "0"))
    sorted_conns = sorted(connections, key=lambda c: -c["priority"])
    if not sorted_conns:
        return {"error": "No connections"}
    idx = rr_index % len(sorted_conns)
    await pm.set_config(idx_key, str((idx + 1) % len(sorted_conns)))
    conn = sorted_conns[idx]
    models = conn["models"]
    return _make_result(conn, models[0] if models else "")


def _cheapest_select(connections: list[dict]) -> dict:
    """Cheapest: pick lowest priority (user-assigned) but available."""
    sorted_conns = sorted(connections, key=lambda c: c["priority"])
    for conn in sorted_conns:
        models = conn["models"]
        if models:
            return _make_result(conn, models[0])
    if sorted_conns:
        return _make_result(sorted_conns[0], "")
    return {"error": "No connections"}


async def _auto_select(connections: list[dict], user_input: str,
                       preferred: str) -> dict:
    """Auto: smart selection based on budget + rate limits + reliability.
    
    - If budget remaining < 20%: use cheapest
    - If user_input is simple (short, greeting): use cheap/fast model
    - If preferred model set: try it, fallback to alternatives
    - Default: sort by reliability (success rate desc, latency asc) then fallback
    """
    budget = await tracker.get_budget()
    
    # Budget threshold: <20% remaining → cheapest
    if budget["limit"] > 0 and budget["used"] > 0:
        ratio = budget["used"] / budget["limit"]
        if ratio > 0.8:
            return _cheapest_select(connections)
    
    # Simple/very short input → use cheapest to save tokens
    if user_input and len(user_input.strip()) < 10:
        return _cheapest_select(connections)
    
    # Short input → use high priority but non-rate-limited
    if user_input and len(user_input.strip()) < 30:
        sorted_conns = sorted(connections, key=lambda c: -c["priority"])
        for conn in sorted_conns:
            if conn["models"]:
                return _make_result(conn, conn["models"][0])
        if sorted_conns:
            return _make_result(sorted_conns[0], "")
    
    # Preferred model → try to match
    if preferred:
        return _manual_select(connections, preferred)
    
    # Default: reliability-aware selection
    return await _reliability_select(connections)


async def _reliability_select(connections: list[dict]) -> dict:
    """Select provider based on reliability: sort by success rate desc, latency asc."""
    # Get reliability data for all connections
    reliabilities = {}
    for conn in connections:
        pid = conn.get("connection_id", "")
        if pid:
            reliabilities[pid] = await tracker.get_reliability(pid)
    
    # Score each connection: higher = better
    def score(conn: dict) -> float:
        pid = conn.get("connection_id", "")
        rel = reliabilities.get(pid, {})
        success_rate = rel.get("success_rate", 100.0)
        avg_latency = rel.get("avg_latency_ms", 0)
        priority = conn.get("priority", 0)
        
        # Score: success_rate (weight 60) + priority (weight 30) - latency penalty (weight 10)
        latency_penalty = min(avg_latency / 100, 20) if avg_latency > 0 else 0
        return (success_rate * 0.6) + (priority * 3) - latency_penalty
    
    sorted_conns = sorted(connections, key=score, reverse=True)
    
    for conn in sorted_conns:
        models = conn["models"]
        if models:
            return _make_result(conn, models[0])
    if sorted_conns:
        return _make_result(sorted_conns[0], "")
    return {"error": "No connections"}


# Default model mapping for virtual unified models
VIRTUAL_MODELS = {
    "yth-hybrid": {
        "coding": "Coding_first",
        "cf": "@cf/zai-org/glm-4.7-flash",
        "openrouter": "google/gemma-4-31b-it:free",
        "nvidia": "nvidia/nemotron-4-340b-instruct",
        "gitlawb": "mimo-v2.5-pro",
        "1": "mimo-v2.5-pro",  # github prefix is "1"
        "freetheai": "bbl/gemini-3.0-flash",
        "xai": "grok-4",
    }
}


def _make_result(conn: dict, model: str) -> dict:
    """Build result dict from connection + model."""
    prefix = conn.get("prefix", "")
    display = f"{prefix}/{model}" if prefix and model else (prefix or model)
    return {
        "provider": conn["provider"],
        "connection_id": conn.get("connection_id", ""),
        "provider_id": conn.get("provider_id", ""),
        "model": model,
        "display_model": display,
        "strategy": settings.get("strategy", "mode", default=AUTO),
    }


async def get_strategy_info() -> dict:
    """Get current strategy state for display."""
    strategy = await get_active_strategy()
    budget = await tracker.get_budget()
    connections = await _get_all_connections()
    limited = 0
    for c in connections:
        if await tracker.is_rate_limited(c.get("connection_id", "")):
            limited += 1
    
    return {
        "strategy": strategy,
        "total_connections": len(connections),
        "rate_limited": limited,
        "available": len(connections) - limited,
        "budget": budget,
        "daily_used": budget["used"],
        "daily_limit": budget["limit"],
    }

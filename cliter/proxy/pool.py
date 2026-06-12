"""Provider connection pool — auto-failover on rate limits, retry logic."""
import asyncio
import json
import time
import httpx
from cliter.proxy import manager as pm
from cliter.proxy import tracker
from cliter.proxy.strategy import select_model, get_active_strategy
from cliter.utils.log import get_logger

log = get_logger("pool")

MAX_RETRIES = 3


async def execute_request(method: str, upstream_url: str, headers: dict,
                          body: dict, stream: bool = False,
                          provider_id: str = "", connection_id: str = "",
                          model: str = "", retry_count: int = 0) -> dict:
    """Execute request with retry logic. Handles 429 with failover.
    Tracks reliability: success rate, latency.
    """
    import time
    start_ts = time.time()

    if retry_count >= MAX_RETRIES:
        await tracker.record_failure(provider_id)
        return {"error": "Max retries exceeded", "status": 503}

    try:
        if stream:
            return await _execute_stream(upstream_url, headers, body)
        else:
            return await _execute_sync(upstream_url, headers, body)
    except Exception as e:
        err_str = str(e).lower()
        latency = (time.time() - start_ts) * 1000

        if "429" in err_str or "rate limit" in err_str or "too many requests" in err_str:
            cooldown = await tracker.record_429(connection_id)
            await tracker.record_failure(provider_id)
            log.warning(f"Rate limited on {connection_id}, cooldown {cooldown}s")

            # Try to find alternative connection
            alt = await _find_alternative(provider_id)
            if alt and retry_count < MAX_RETRIES - 1:
                log.info(f"Failing over to {alt.get('connection_id','?')}")
                alt_url = alt["base_url"].rstrip("/")
                if not alt_url.endswith("/v1"):
                    alt_url = f"{alt_url}/v1"
                alt_headers = {"Content-Type": "application/json"}
                if alt.get("api_key"):
                    alt_headers["Authorization"] = f"Bearer {alt['api_key']}"

                return await execute_request(
                    method=method,
                    upstream_url=f"{alt_url}/chat/completions",
                    headers=alt_headers,
                    body=body,
                    stream=stream,
                    provider_id=alt.get("provider_id", provider_id),
                    connection_id=alt.get("connection_id", ""),
                    model=model,
                    retry_count=retry_count + 1,
                )
        else:
            await tracker.record_failure(provider_id)
            await tracker.record_429(connection_id)

        return {"error": str(e), "status": getattr(e, "status_code", 502)}


async def _execute_sync(url: str, headers: dict, body: dict) -> dict:
    import time
    start = time.time()
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(url, json=body, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    latency = (time.time() - start) * 1000
    pid = body.get("_provider_id", "")
    cid = body.get("_connection_id", "")

    # Track success + latency
    if pid:
        await tracker.record_success_latency(pid, latency)
    if cid:
        await tracker.record_success(cid)

    usage = data.get("usage", {})
    if usage:
        await tracker.log_usage(
            provider_id=pid,
            connection_id=cid,
            model=body.get("model", ""),
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
        )
    return {"response": data, "status": resp.status_code}


async def _execute_stream(url: str, headers: dict, body: dict) -> dict:
    """Streaming execution — returns async generator."""
    async def _stream():
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream("POST", url, json=body, headers=headers) as resp:
                if resp.status_code != 200:
                    error_body = await resp.aread()
                    yield {"error": error_body.decode(), "status": resp.status_code}
                    return
                
                usage_data = {}
                async for chunk in resp.aiter_bytes():
                    yield {"chunk": chunk, "status": 200}
                    # Track SSE data for token counting
                    if chunk.startswith(b"data: "):
                        line = chunk[6:].strip()
                        if line and line != b"[DONE]":
                            try:
                                import json as j
                                d = j.loads(line)
                                if "usage" in d:
                                    usage_data = d["usage"]
                            except Exception:
                                pass
                
                # Log usage after stream completes
                if usage_data:
                    await tracker.log_usage(
                        provider_id=body.get("_provider_id", ""),
                        connection_id=body.get("_connection_id", ""),
                        model=body.get("model", ""),
                        prompt_tokens=usage_data.get("prompt_tokens", 0),
                        completion_tokens=usage_data.get("completion_tokens", 0),
                    )
    
    return {"stream": _stream(), "status": 200}


async def _find_alternative(provider_id: str) -> dict | None:
    """Find another connection for the same or different provider."""
    providers = await pm.list_providers()
    # Try same provider first
    for p in providers:
        if p.get("id") == provider_id or p.get("name", "").lower() == provider_id.lower():
            # Check if has other API keys (future: multi-key per provider)
            pass
    
    # Find any non-rate-limited provider
    for p in providers:
        if not p["is_active"]:
            continue
        cid = p.get("id", "")
        if not await tracker.is_rate_limited(cid) and p.get("api_key"):
            return {
                "connection_id": cid,
                "base_url": p.get("base_url", ""),
                "api_key": p.get("api_key", ""),
            }
    
    # Last resort: any provider with key
    for p in providers:
        if p.get("api_key"):
            return {
                "connection_id": p.get("id", ""),
                "base_url": p.get("base_url", ""),
                "api_key": p.get("api_key", ""),
            }
    
    return None


async def test_connection(provider_id: str) -> dict:
    """Test a provider connection by hitting /v1/models."""
    providers = await pm.list_providers()
    target = None
    for p in providers:
        if p.get("id") == provider_id or p.get("name", "").lower() == provider_id.lower():
            target = p
            break
    if not target:
        return {"ok": False, "error": "Provider not found"}
    
    base = target["base_url"].rstrip("/")
    headers = {"Authorization": f"Bearer {target['api_key']}"} if target.get("api_key") else {}
    
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.get(f"{base}/models", headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                model_count = len(data.get("data", []))
                return {"ok": True, "models": model_count, "status": 200}
            else:
                return {"ok": False, "error": f"HTTP {resp.status_code}", "status": resp.status_code}
    except Exception as e:
        return {"ok": False, "error": str(e)}

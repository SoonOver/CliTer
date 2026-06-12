"""Auto monitor — health checks, model sync, auto enable/disable."""
import asyncio
import json
import time
import httpx
import aiosqlite
from cliter.proxy import manager as pm
from cliter.proxy import tracker
from cliter.utils.log import get_logger

log = get_logger("monitor")

CHECK_INTERVAL = 60        # seconds between full health checks
MODEL_SYNC_INTERVAL = 300  # seconds between model syncs (5min)
FAIL_THRESHOLD = 3         # consecutive failures before auto-disable
RECOVERY_INTERVAL = 120    # seconds before re-testing a disabled provider
SLOW_THRESHOLD_MS = 5000   # response time above this = degraded

_monitor_task: asyncio.Task | None = None
_running = False


async def start(interval: int = CHECK_INTERVAL):
    """Start background health monitor loop."""
    global _monitor_task, _running
    if _running:
        return
    _running = True
    _monitor_task = asyncio.create_task(_run_loop(interval))
    log.info("Health monitor started")


async def stop():
    global _monitor_task, _running
    _running = False
    if _monitor_task:
        _monitor_task.cancel()
        _monitor_task = None
    log.info("Health monitor stopped")


async def _run_loop(interval: int):
    """Main monitor loop."""
    last_model_sync = 0
    while _running:
        try:
            await run_health_check(log_results=False)
            
            # Periodic model sync
            if time.time() - last_model_sync > MODEL_SYNC_INTERVAL:
                synced = await sync_all_models()
                if synced > 0:
                    log.info(f"Auto-synced {synced} provider model lists")
                last_model_sync = time.time()
                
        except Exception as e:
            log.warning(f"Monitor loop error: {e}")
        
        await asyncio.sleep(interval)


async def run_health_check(log_results: bool = True) -> dict:
    """Ping all providers, update their health status. Returns summary."""
    providers = await pm.list_providers()
    results = {"healthy": 0, "degraded": 0, "dead": 0, "recovered": 0}
    
    for p in providers:
        pid = p["id"]
        name = p["name"]
        base_url = p["base_url"]
        api_key = p.get("api_key", "")
        is_active = p.get("is_active", 1)
        
        if not base_url:
            continue
        
        # Skip if in cooldown from rate limit
        if await tracker.is_rate_limited(pid):
            continue
        
        # Build clean URL
        url = base_url.rstrip("/")
        if not url.endswith("/v1"):
            url = f"{url}/v1"
        url = f"{url}/models"
        
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        
        start_ms = time.time() * 1000
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                resp = await c.get(url, headers=headers)
            
            elapsed = (time.time() * 1000) - start_ms
            
            if resp.status_code == 200:
                # Healthy
                if not is_active:
                    # Provider was dead, now recovered
                    await pm.set_active(pid, True)
                    await tracker.record_success(pid)
                    results["recovered"] += 1
                    log.info(f"Provider {name} recovered, re-enabled")
                results["healthy"] += 1
            elif resp.status_code == 401 or resp.status_code == 403:
                # Auth error — probably bad key, mark as degraded but keep active
                results["degraded"] += 1
                log.warning(f"Provider {name} auth error (HTTP {resp.status_code})")
            else:
                # Non-200 — increment failure count
                await _record_failure(p, pid, name, is_active, results)
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadTimeout):
            elapsed = (time.time() * 1000) - start_ms
            await _record_failure(p, pid, name, is_active, results)
        except Exception as e:
            elapsed = (time.time() * 1000) - start_ms
            await _record_failure(p, pid, name, is_active, results)
    
    if log_results and results["dead"] > 0:
        log.info(f"Health check: {results['healthy']} healthy, {results['degraded']} degraded, {results['dead']} dead, {results['recovered']} recovered")
    
    return results


async def _record_failure(p: dict, pid: str, name: str, is_active: bool, results: dict):
    """Record a failure, auto-disable if threshold exceeded."""
    fail_key = f"_fail_count_{pid}"
    current_fails = await pm.get_config(fail_key, "0")
    fails = int(current_fails) + 1
    
    if fails >= FAIL_THRESHOLD and is_active:
        await pm.set_active(pid, False)
        log.warning(f"Provider {name} auto-disabled after {fails} consecutive failures")
        results["dead"] += 1
        # Reset fail counter after disabling
        await pm.set_config(fail_key, "0")
    else:
        await pm.set_config(fail_key, str(fails))
        results["degraded"] += 1


async def test_provider(provider_id: str) -> dict:
    """Test a single provider connection. Returns detailed result."""
    providers = await pm.list_providers()
    p = None
    for prov in providers:
        if prov["id"] == provider_id or prov["name"].lower() == provider_id.lower():
            p = prov
            break
    
    if not p:
        return {"ok": False, "error": "Provider not found"}
    
    base_url = p["base_url"].rstrip("/")
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1"
    
    headers = {"Authorization": f"Bearer {p['api_key']}"} if p.get("api_key") else {}
    
    try:
        start = time.time()
        async with httpx.AsyncClient(timeout=10) as c:
            resp = await c.get(f"{base_url}/models", headers=headers)
        elapsed = round((time.time() - start) * 1000)
        
        if resp.status_code == 200:
            data = resp.json()
            model_list = [m["id"] for m in data.get("data", [])[:20]]
            return {
                "ok": True,
                "status": 200,
                "latency_ms": elapsed,
                "models": model_list,
                "model_count": len(data.get("data", [])),
            }
        else:
            return {"ok": False, "error": f"HTTP {resp.status_code}", "status": resp.status_code, "latency_ms": elapsed}
    except httpx.TimeoutException:
        return {"ok": False, "error": "timeout", "latency_ms": -1}
    except Exception as e:
        return {"ok": False, "error": str(e), "latency_ms": -1}


async def sync_all_models() -> int:
    """Query each provider's /v1/models and update their model list. Returns count of updated providers."""
    providers = await pm.list_providers()
    updated = 0
    
    for p in providers:
        if not p["is_active"]:
            continue
        if not p.get("api_key"):
            continue
        
        base_url = p["base_url"].rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"
        
        headers = {"Authorization": f"Bearer {p['api_key']}"} if p.get("api_key") else {}
        
        try:
            async with httpx.AsyncClient(timeout=5) as c:
                resp = await c.get(f"{base_url}/models", headers=headers)
            
            if resp.status_code == 200:
                data = resp.json()
                models = [m["id"] for m in data.get("data", [])]
                
                if models:
                    existing_models = json.loads(p.get("models", "[]"))
                    # Only update if new models found (don't overwrite manual config)
                    if len(models) > len(existing_models):
                        from cliter.proxy import manager as pm2
                        async with aiosqlite.connect(pm2.DB) as db:
                            await db.execute(
                                "UPDATE proxy_providers SET models=?, updated_at=? WHERE id=?",
                                (json.dumps(models), time.time(), p["id"])
                            )
                            await db.commit()
                        updated += 1
        except Exception:
            pass
    
    return updated


async def get_monitor_status() -> dict:
    """Get current monitor status for display."""
    providers = await pm.list_providers()
    active_count = sum(1 for p in providers if p["is_active"])
    inactive_count = len(providers) - active_count
    
    # Count rate-limited
    limited = 0
    for p in providers:
        if await tracker.is_rate_limited(p["id"]):
            limited += 1
    
    return {
        "running": _running,
        "total_providers": len(providers),
        "active": active_count,
        "inactive": inactive_count,
        "rate_limited": limited,
        "check_interval": CHECK_INTERVAL,
    }

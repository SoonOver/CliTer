"""9Router DB importer — extract providers + API keys into CliTer proxy."""
import sqlite3
import json
import os
from pathlib import Path
from cliter.utils.log import get_logger

log = get_logger("9router")

# Known base URLs for common providers (OpenAI-compatible endpoint)
KNOWN_PROVIDERS = {
    "openrouter":    {"base_url": "https://openrouter.ai/api/v1",        "prefix": "openrouter"},
    "nvidia":        {"base_url": "https://integrate.api.nvidia.com/v1", "prefix": "nvidia"},
    "xai":           {"base_url": "https://api.x.ai/v1",                 "prefix": "xai"},
    "cloudflare-ai": {"base_url": None,  "prefix": "cf"},  # needs accountId
}

# Default base URLs when providerSpecificData doesn't have one
FALLBACK_BASE_URLS = {
    "openrouter": "https://openrouter.ai/api/v1",
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "xai": "https://api.x.ai/v1",
}


def find_db() -> str | None:
    """Locate 9Router's SQLite DB on this machine."""
    candidates = [
        # Windows
        os.path.expandvars(r"%APPDATA%\9router\db\data.sqlite"),
        # Linux / Termux
        os.path.expanduser("~/.9router/db/data.sqlite"),
        # macOS
        os.path.expanduser("~/Library/Application Support/9router/db/data.sqlite"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return None


def extract_api_keys(db_path: str) -> tuple:
    """Extract 9Router's own API key + all upstream provider API keys.
    
    Returns (proxy_keys: list, providers: list[dict])
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # 1. 9Router's own API keys
    proxy_keys = []
    cur = conn.execute("SELECT * FROM apiKeys")
    for r in cur.fetchall():
        d = dict(r)
        proxy_keys.append({"key": d["key"], "name": d.get("name", ""), "active": d["isActive"]})
    
    # 2. Provider nodes
    cur = conn.execute("SELECT * FROM providerNodes")
    nodes = {r["id"]: dict(r) for r in cur.fetchall()}
    
    # 3. Connections
    cur = conn.execute("SELECT * FROM providerConnections")
    connections = [dict(r) for r in cur.fetchall()]
    
    # 4. Combos — extract prefix→models mapping
    cur = conn.execute("SELECT * FROM combos")
    combos = [dict(r) for r in cur.fetchall()]
    
    # Build prefix→models from combos
    prefix_models = {}
    for combo in combos:
        models_list = json.loads(combo.get("models", "[]"))
        for model in models_list:
            if "/" in model:
                prefix = model.split("/", 1)[0]
                # Strip prefix to get actual upstream model name
                rest = model[len(prefix)+1:]
                if prefix not in prefix_models:
                    prefix_models[prefix] = set()
                # deduplicate: store the full model name as shown
                prefix_models[prefix].add(rest)
    
    # 5. Build provider list
    imported = []
    skipped = []

    # 6. Build model aliases from kv table
    model_aliases = {}
    try:
        cur = conn.execute("SELECT * FROM kv WHERE scope='modelAliases'")
        for r in cur.fetchall():
            alias = r["key"]
            target = json.loads(r["value"])
            model_aliases[alias] = target
    except Exception:
        pass

    # Build prefix aliases from combos + model aliases
    prefix_aliases = {}
    node_prefixes = set()
    for nid, n in nodes.items():
        nd = json.loads(n["data"])
        p = nd.get("prefix", "")
        if p and "/" not in p:
            node_prefixes.add(p)
    for conn_data in connections:
        d2 = json.loads(conn_data.get("data", "{}"))
        psd2 = d2.get("providerSpecificData", {})
        if psd2.get("prefix") and "/" not in psd2["prefix"]:
            node_prefixes.add(psd2["prefix"])

    for combo in combos:
        combo_models = json.loads(combo.get("models", "[]"))
        for model_name in combo_models:
            if "/" not in model_name:
                continue
            cp = model_name.split("/", 1)[0]
            if cp in node_prefixes:
                continue
            for alias_key, alias_target in model_aliases.items():
                if alias_target.startswith(f"{cp}/") or alias_key == model_name:
                    for nid, n in nodes.items():
                        if nid in alias_target:
                            nd = json.loads(n["data"])
                            actual_prefix = nd.get("prefix", "")
                            if actual_prefix and actual_prefix != cp and "/" not in actual_prefix:
                                prefix_aliases[cp] = actual_prefix
                                break
                    break

    for conn_data in connections:
        conn_id = conn_data["provider"]
        name = conn_data.get("name", "unknown")
        data = json.loads(conn_data.get("data", "{}"))
        psd = data.get("providerSpecificData", {})
        api_key = data.get("apiKey", "") or ""

        # Also check providerSpecificData for auth tokens (xAI idToken, GitHub copilotToken, etc.)
        if not api_key:
            for key_field in ("idToken", "copilotToken", "accessToken", "token", "clientSecret"):
                val = psd.get(key_field) or data.get(key_field)
                if val and len(str(val)) > 8:
                    api_key = str(val)
                    break
        
        test_status = data.get("testStatus", "unknown")
        
        # Check if this connection has full data in providerSpecificData
        if psd.get("baseUrl") and (psd.get("prefix") or api_key):
            # Full node-based connection
            psd_prefix = psd.get("prefix", "")
            base_url = psd["baseUrl"]
            node_name = psd.get("nodeName", name)

            # Resolve prefix: try multiple sources in order
            prefix = ""
            node_id = conn_id if conn_id in nodes else None

            # 1. Try providerNode's data.prefix
            if not node_id:
                for nid, n in nodes.items():
                    if n["name"].lower() == node_name.lower():
                        node_id = nid
                        break
            if node_id:
                node_data = json.loads(nodes[node_id]["data"])
                node_prefix = node_data.get("prefix", "")
                if node_prefix and "/" not in node_prefix:
                    prefix = node_prefix

            # 2. If node prefix looks wrong, try combo prefix that matches node name
            if not prefix or "/" in prefix:
                for cp in sorted(prefix_models.keys(), key=lambda x: -len(x)):
                    if cp == node_name.lower() or node_name.lower().startswith(cp) or cp.startswith(node_name.lower()):
                        prefix = cp
                        break

            # 2b. Try matching combo prefix by checking which combo models contain the node name or node UUID
            if not prefix or "/" in prefix:
                node_name_lower = node_name.lower()
                node_id_short = node_id[:20] if node_id else ""
                for cp, models in prefix_models.items():
                    for m in models:
                        if node_name_lower in m.lower() or (node_id_short and node_id_short in m):
                            prefix = cp
                            break
                    if prefix:
                        break

            # 3. Try matching psd_prefix against combo prefixes (clean version)
            if not prefix or "/" in psd_prefix:
                clean = psd_prefix.split("/")[-1] if "/" in psd_prefix else psd_prefix
                for cp in prefix_models:
                    if cp == clean or cp == clean.lower():
                        prefix = cp
                        break

            # 4. Last resort: use psd_prefix if it doesn't have "/"
            if not prefix and "/" not in psd_prefix:
                prefix = psd_prefix

            # 5. Absolute fallback: use node_name lowercase
            if not prefix:
                prefix = node_name.lower().replace(" ", "-")

            # Get models for this prefix
            models = list(prefix_models.get(prefix, []))
            if not models and node_id:
                node_data = json.loads(nodes[node_id]["data"])
                if node_data.get("models"):
                    models = [m for m in node_data["models"] if m]
            
            if api_key:
                imported.append({
                    "name": node_name or name,
                    "prefix": prefix,
                    "base_url": base_url.rstrip("/"),
                    "api_key": api_key,
                    "models": models,
                    "status": test_status,
                    "source": "node",
                })
            else:
                skipped.append({"name": name, "reason": "no API key", "prefix": prefix})
            continue
        
        # 6. Known providers (no node in DB, but 9Router knows them)
        provider_name = conn_id  # provider field IS the provider name for these
        
        if provider_name in KNOWN_PROVIDERS:
            info = KNOWN_PROVIDERS[provider_name]
            if provider_name == "cloudflare-ai" and psd.get("accountId"):
                base_url = f"https://api.cloudflare.com/client/v4/accounts/{psd['accountId']}/ai/v1"
            elif info["base_url"]:
                base_url = info["base_url"]
            else:
                skipped.append({"name": name, "reason": "missing accountId for Cloudflare", "prefix": info["prefix"]})
                continue
            
            prefix = info["prefix"]
            models = list(prefix_models.get(prefix, []))
            
            if api_key and len(api_key) > 4:
                imported.append({
                    "name": provider_name.capitalize(),
                    "prefix": prefix,
                    "base_url": base_url,
                    "api_key": api_key,
                    "models": models,
                    "status": test_status,
                    "source": "known",
                })
            else:
                skipped.append({"name": provider_name, "reason": "no/empty API key", "prefix": prefix})
        else:
            # Unknown provider — log for user review
            has_key = bool(api_key and len(api_key) > 4)
            skipped.append({
                "name": f"{provider_name} ({name})",
                "reason": "unknown provider type" if not has_key else "unknown but has API key (needs base URL)",
                "prefix": "",
            })
    
    conn.close()
    
    # Also extract model prefixes from combos for user reference
    all_prefixes = sorted(prefix_models.keys())
    
    # Identify unaccounted combo prefixes
    all_provider_prefixes = set(p["prefix"] for p in imported if p["prefix"])
    combo_prefix_set = set(all_prefixes)
    unaccounted_prefixes = sorted(combo_prefix_set - all_provider_prefixes - set(prefix_aliases.keys()))
    
    return proxy_keys, imported, skipped, all_prefixes, combos, prefix_aliases, unaccounted_prefixes


async def import_into_cliter(db_path: str | None = None) -> dict:
    """Import 9Router providers into CliTer proxy. Returns summary dict."""
    import aiosqlite, json, time
    from cliter.proxy import manager as pm
    
    if db_path is None:
        db_path = find_db()
    
    if not db_path:
        return {"ok": False, "error": "9Router database not found"}
    
    proxy_keys, imported, skipped, all_prefixes, _, prefix_aliases, unaccounted = extract_api_keys(db_path)
    
    # Store prefix aliases
    if prefix_aliases:
        existing = await pm.get_model_aliases()
        existing.update(prefix_aliases)
        await pm.set_model_aliases(existing)
    
    results = []
    for prov in imported:
        try:
            # Check if already exists (by name or prefix)
            existing = await pm.get_provider(prov["prefix"])
            existing_name = await pm.get_provider(prov["name"])
            if existing or existing_name:
                ident = existing["id"] if existing else existing_name["id"]
                async with aiosqlite.connect(pm.DB) as db:
                    await db.execute(
                        "UPDATE proxy_providers SET base_url=?, api_key=?, models=?, updated_at=? WHERE id=?",
                        (prov["base_url"], prov["api_key"], json.dumps(prov["models"]), time.time(), ident)
                    )
                    await db.commit()
                results.append({"name": prov["name"], "status": "updated"})
            else:
                await pm.add_provider(
                    name=prov["name"],
                    prefix=prov["prefix"],
                    base_url=prov["base_url"],
                    api_key=prov["api_key"],
                    models=prov["models"],
                    priority=10 if prov["status"] == "active" else 0,
                )
                results.append({"name": prov["name"], "status": "imported"})
        except Exception as e:
            results.append({"name": prov["name"], "status": f"error: {e}"})
    
    return {
        "ok": True,
        "db_path": db_path,
        "proxy_keys": [k["key"][:12]+"..." for k in proxy_keys],
        "imported": results,
        "skipped": skipped,
        "all_prefixes": sorted(all_prefixes),
        "prefix_aliases": prefix_aliases,
        "unaccounted_prefixes": unaccounted,
        "provider_count": len(imported),
    }

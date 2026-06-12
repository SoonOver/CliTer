"""Request routing — match model prefix to upstream provider."""
from cliter.proxy import manager

async def route(model: str) -> tuple[dict | None, str]:
    """Route a model name to its provider and stripped model name.
    
    Returns (provider_dict, stripped_model) or (None, model) if no match.
    
    Examples:
        'kr/gpt-4o' -> (kr_provider, 'gpt-4o')
        'gpt-4o' -> (default_provider, 'gpt-4o')
        'gh/claude' -> resolves alias 'gh'->'1', then routes to '1' provider
    """
    providers = await manager.list_providers()
    active = [p for p in providers if p["is_active"]]
    aliases = await manager.get_model_aliases()
    
    resolved_model = model
    
    # 1. Check alias resolution first
    if "/" in model:
        prefix, stripped = model.split("/", 1)
        # Check if prefix is an alias for another provider
        if prefix in aliases:
            actual_prefix = aliases[prefix]
            # Find provider with actual prefix
            for p in active:
                if p["prefix"] == actual_prefix:
                    return p, stripped
            # If no direct match, prepend actual prefix to model for re-routing
            resolved_model = f"{actual_prefix}/{stripped}"
    
    # 2. Check prefix match
    if "/" in resolved_model:
        prefix, stripped = resolved_model.split("/", 1)
        for p in active:
            if p["prefix"] == prefix:
                return p, stripped
    
    # 3. Direct model match
    import json
    for p in active:
        prov_models = json.loads(p.get("models", "[]"))
        if model in prov_models:
            return p, model
    
    # 4. Default provider
    default_name = await manager.get_default()
    if default_name:
        for p in active:
            if p["name"] == default_name:
                return p, model
    
    # 5. First active
    if active:
        return active[0], model
    
    return None, model

async def resolve_base_url(provider: dict) -> str:
    """Ensure base_url has proper format."""
    url = provider["base_url"].rstrip("/")
    if not url.endswith("/v1"):
        # Check if it already has chat/completions path
        if "/chat/completions" in url:
            url = url.split("/chat/completions")[0]
        url = url.rstrip("/")
    return url

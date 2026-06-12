from cliter.llm.base import BaseLLMProvider
from cliter.llm.openai_compat import OpenAICompatProvider

def get_provider(name: str = None) -> BaseLLMProvider:
    from cliter.config import settings

    # If proxy is enabled + auto_use, default to proxy
    proxy_enabled = settings.get("proxy", "enabled", default=False)
    proxy_auto = settings.get("proxy", "auto_use", default=True)
    if proxy_enabled and proxy_auto and (name is None or name == "openai"):
        proxy_host = settings.get("proxy", "host", default="127.0.0.1")
        proxy_port = settings.get("proxy", "port", default=20129)
        proxy_key = settings.get("proxy", "api_key", default="cliter-proxy-key")
        return OpenAICompatProvider(
            override_base_url=f"http://{proxy_host}:{proxy_port}",
            override_api_key=proxy_key,
        )

    name = name or settings.get("llm", "provider", default="openai")
    if name in ("openai", "openrouter", "ollama", "lmstudio", "local"):
        return OpenAICompatProvider()
    if name == "proxy":
        proxy_host = settings.get("proxy", "host", default="127.0.0.1")
        proxy_port = settings.get("proxy", "port", default=20129)
        proxy_key = settings.get("proxy", "api_key", default="cliter-proxy-key")
        return OpenAICompatProvider(
            override_base_url=f"http://{proxy_host}:{proxy_port}",
            override_api_key=proxy_key,
        )
    raise ValueError(f"Unknown provider: {name}")

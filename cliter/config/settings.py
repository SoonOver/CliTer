"""YAML config loader with defaults + user override."""
import yaml
from pathlib import Path
from typing import Any
from cliter.utils.paths import config_path

_DEFAULTS_PATH = Path(__file__).parent / "defaults.yaml"
_config: dict = {}

def _deep_merge(base: dict, override: dict) -> dict:
    out = base.copy()
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out

def load() -> dict:
    global _config
    with open(_DEFAULTS_PATH) as f:
        defaults = yaml.safe_load(f) or {}
    user_path = config_path()
    user = {}
    if user_path.exists():
        with open(user_path) as f:
            user = yaml.safe_load(f) or {}
    _config = _deep_merge(defaults, user)
    return _config

def get(*keys: str, default: Any = None) -> Any:
    """Dot-path access: get('llm', 'model')"""
    if not _config:
        load()
    node = _config
    for k in keys:
        if isinstance(node, dict) and k in node:
            node = node[k]
        else:
            return default
    return node

def set_val(*keys: str, value: Any):
    """Set nested key. Does NOT persist to file."""
    if not _config:
        load()
    node = _config
    for k in keys[:-1]:
        if k not in node:
            node[k] = {}
        node = node[k]
    node[keys[-1]] = value

def save_user():
    """Persist current config to user config file."""
    import copy
    with open(_DEFAULTS_PATH) as f:
        defaults = yaml.safe_load(f) or {}
    # only save diffs from defaults
    def _diff(base, current):
        out = {}
        for k, v in current.items():
            if k not in base:
                out[k] = v
            elif isinstance(v, dict) and isinstance(base.get(k), dict):
                d = _diff(base[k], v)
                if d:
                    out[k] = d
            elif v != base.get(k):
                out[k] = v
        return out
    diff = _diff(defaults, _config)
    if diff:
        with open(config_path(), "w") as f:
            yaml.dump(diff, f, default_flow_style=False)

def proxy_config(key: str, default=None):
    """Shorthand for proxy config keys."""
    return get("proxy", key, default=default)

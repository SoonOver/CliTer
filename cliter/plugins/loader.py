"""Plugin loader — discovers and loads plugins from ~/.cliter/plugins/."""
import importlib, sys
from pathlib import Path
from cliter.utils.paths import home_dir
from cliter.utils.log import get_logger

log = get_logger("plugins")

def load_plugins():
    """Load all plugins from ~/.cliter/plugins/."""
    plugins_dir = home_dir() / "plugins"
    plugins_dir.mkdir(exist_ok=True)

    for p in plugins_dir.iterdir():
        if p.is_dir() and (p / "__init__.py").exists():
            try:
                sys.path.insert(0, str(plugins_dir))
                mod = importlib.import_module(p.name)
                if hasattr(mod, "register"):
                    mod.register()
                    log.info(f"Loaded plugin: {p.name}")
            except Exception as e:
                log.warning(f"Failed to load plugin {p.name}: {e}")
        elif p.suffix == ".py" and p.name != "__init__.py":
            try:
                sys.path.insert(0, str(plugins_dir))
                mod = importlib.import_module(p.stem)
                if hasattr(mod, "register"):
                    mod.register()
                    log.info(f"Loaded plugin: {p.stem}")
            except Exception as e:
                log.warning(f"Failed to load plugin {p.stem}: {e}")

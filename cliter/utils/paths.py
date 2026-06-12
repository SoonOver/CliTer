"""Path resolution for CliTer. Termux-aware."""
import os
from pathlib import Path

def is_termux() -> bool:
    return os.path.isdir("/data/data/com.termux")

def home_dir() -> Path:
    """~/.cliter/ — config, skills, memory, sessions."""
    base = Path.home() / ".cliter"
    base.mkdir(parents=True, exist_ok=True)
    return base

def config_path() -> Path:
    return home_dir() / "config.yaml"

def skills_dir() -> Path:
    d = home_dir() / "skills"
    d.mkdir(exist_ok=True)
    return d

def db_path() -> Path:
    return home_dir() / "cliter.db"

def sessions_dir() -> Path:
    d = home_dir() / "sessions"
    d.mkdir(exist_ok=True)
    return d

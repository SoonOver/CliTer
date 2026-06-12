"""Skill loader — reads YAML frontmatter + markdown body from .md files."""
import yaml
from pathlib import Path
from cliter.utils.paths import skills_dir

def _parse_skill(path: Path) -> dict | None:
    """Parse a SKILL.md file: YAML frontmatter + markdown body."""
    text = path.read_text(errors="replace")
    if not text.startswith("---"):
        return {"name": path.stem, "content": text, "metadata": {}, "path": str(path)}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {"name": path.stem, "content": text, "metadata": {}, "path": str(path)}
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        meta = {}
    body = parts[2].strip()
    return {
        "name": meta.get("name", path.stem),
        "description": meta.get("description", ""),
        "content": body,
        "metadata": meta,
        "path": str(path),
    }

def list_skills() -> list[dict]:
    """List all available skills."""
    skills = []
    sd = skills_dir()
    # flat .md files
    for f in sd.glob("*.md"):
        s = _parse_skill(f)
        if s:
            skills.append(s)
    # subdirectories with SKILL.md
    for d in sd.iterdir():
        if d.is_dir():
            skill_file = d / "SKILL.md"
            if skill_file.exists():
                s = _parse_skill(skill_file)
                if s:
                    skills.append(s)
    return skills

def load_skill(name: str) -> dict | None:
    """Load a skill by name."""
    sd = skills_dir()
    # direct file
    direct = sd / f"{name}.md"
    if direct.exists():
        return _parse_skill(direct)
    # subdir
    subdir = sd / name / "SKILL.md"
    if subdir.exists():
        return _parse_skill(subdir)
    # fuzzy match
    for s in list_skills():
        if s["name"].lower() == name.lower():
            return s
    return None

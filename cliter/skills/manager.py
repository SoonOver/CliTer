"""Skill CRUD."""
from pathlib import Path
from cliter.utils.paths import skills_dir
from cliter.skills.loader import load_skill, list_skills

def create_skill(name: str, content: str, description: str = "") -> str:
    """Create a new skill .md file."""
    sd = skills_dir()
    path = sd / f"{name}.md"
    if path.exists():
        return f"Skill '{name}' already exists"
    frontmatter = f"""---
name: {name}
description: "{description}"
---

{content}
"""
    path.write_text(frontmatter)
    return f"Created skill: {path}"

def delete_skill(name: str) -> str:
    sd = skills_dir()
    path = sd / f"{name}.md"
    if path.exists():
        path.unlink()
        return f"Deleted skill: {name}"
    subdir = sd / name
    if subdir.is_dir():
        import shutil
        shutil.rmtree(subdir)
        return f"Deleted skill dir: {name}"
    return f"Skill '{name}' not found"

def edit_skill(name: str, content: str) -> str:
    sd = skills_dir()
    path = sd / f"{name}.md"
    if not path.exists():
        subdir = sd / name / "SKILL.md"
        if subdir.exists():
            path = subdir
        else:
            return f"Skill '{name}' not found"
    path.write_text(content)
    return f"Updated skill: {path}"

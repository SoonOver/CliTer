"""Self-improvement tools for CliTer agent."""
import os
import yaml
from pathlib import Path
from cliter.tools.base import BaseTool
from cliter.utils.paths import skills_dir, home_dir
from cliter.config import settings

class SelfImproveTool(BaseTool):
    name = "self_improve"
    description = (
        "Improve the AI agent's own capabilities by adding/modifying skills, "
        "creating plugins, or updating settings/prompts."
    )
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add_skill", "add_plugin", "update_setting"],
                "description": "Improvement action to take",
            },
            "name": {
                "type": "string",
                "description": "Skill name, plugin name, or setting key (e.g. agent.system_prompt)",
            },
            "content": {
                "type": "string",
                "description": "YAML markdown content for skills, python code for plugins, or value for settings",
            },
            "description": {
                "type": "string",
                "description": "Brief description of this capability improvement",
            },
        },
        "required": ["action", "name", "content"],
    }

    async def execute(self, action: str, name: str, content: str, description: str = "", **kw) -> str:
        try:
            if action == "add_skill":
                # Save skill to ~/.cliter/skills/name.md
                sd = skills_dir()
                # Clean name
                clean_name = "".join(c for c in name if c.isalnum() or c in "-_").lower()
                if not clean_name.endswith(".md"):
                    file_path = sd / f"{clean_name}.md"
                else:
                    file_path = sd / clean_name
                
                # Check if content has YAML frontmatter, if not add it
                if not content.startswith("---"):
                    desc = description or f"Auto-generated skill: {clean_name}"
                    yaml_header = f"---\nname: {clean_name}\ndescription: {desc}\n---\n"
                    content = yaml_header + content
                
                file_path.write_text(content, encoding="utf-8")
                return f"SUCCESS: New skill '{clean_name}' saved to {file_path}. I will load this in future turns."
                
            elif action == "add_plugin":
                # Save plugin to ~/.cliter/plugins/name.py
                pd = home_dir() / "plugins"
                pd.mkdir(exist_ok=True)
                clean_name = "".join(c for c in name if c.isalnum() or c in "-_").lower()
                if not clean_name.endswith(".py"):
                    file_path = pd / f"{clean_name}.py"
                else:
                    file_path = pd / clean_name
                
                file_path.write_text(content, encoding="utf-8")
                return f"SUCCESS: New plugin code saved to {file_path}. Restart CliTer to load."
                
            elif action == "update_setting":
                # Split key
                keys = name.split(".")
                settings.set_val(*keys, value=content)
                return f"SUCCESS: Config setting '{name}' updated to '{content}'."
                
            else:
                return f"ERROR: Unknown self-improvement action: {action}"
                
        except Exception as e:
            return f"ERROR during self-improvement: {e}"

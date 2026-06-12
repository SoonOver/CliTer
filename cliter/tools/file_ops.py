"""File operation tools."""
import os, re
from pathlib import Path
from cliter.tools.base import BaseTool

class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read a text file. Returns numbered lines."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path"},
            "offset": {"type": "integer", "description": "Start line (1-indexed)", "default": 1},
            "limit": {"type": "integer", "description": "Max lines to read", "default": 200},
        },
        "required": ["path"],
    }

    async def execute(self, path: str, offset: int = 1, limit: int = 200, **kw) -> str:
        try:
            p = Path(path).expanduser()
            if not p.exists():
                return f"ERROR: file not found: {path}"
            lines = p.read_text(errors="replace").splitlines()
            total = len(lines)
            start = max(0, offset - 1)
            end = min(total, start + limit)
            out = []
            for i in range(start, end):
                out.append(f"{i+1}|{lines[i]}")
            return f"total_lines: {total}\n" + "\n".join(out)
        except Exception as e:
            return f"ERROR: {e}"

class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Write content to a file (overwrites)."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path"},
            "content": {"type": "string", "description": "File content"},
        },
        "required": ["path", "content"],
    }

    async def execute(self, path: str, content: str, **kw) -> str:
        try:
            p = Path(path).expanduser()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            return f"OK: wrote {len(content)} bytes to {p}"
        except Exception as e:
            return f"ERROR: {e}"

class PatchFileTool(BaseTool):
    name = "patch_file"
    description = "Find and replace text in a file."
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path"},
            "old_string": {"type": "string", "description": "Text to find"},
            "new_string": {"type": "string", "description": "Replacement text"},
        },
        "required": ["path", "old_string", "new_string"],
    }

    async def execute(self, path: str, old_string: str, new_string: str, **kw) -> str:
        try:
            p = Path(path).expanduser()
            text = p.read_text(errors="replace")
            count = text.count(old_string)
            if count == 0:
                return "ERROR: old_string not found in file"
            text = text.replace(old_string, new_string, 1)
            p.write_text(text)
            return f"OK: replaced 1 occurrence in {p}"
        except Exception as e:
            return f"ERROR: {e}"

class SearchFilesTool(BaseTool):
    name = "search_files"
    description = "Search file contents (grep) or find files by name."
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Search pattern (regex for content, glob for files)"},
            "path": {"type": "string", "description": "Directory to search", "default": "."},
            "target": {"type": "string", "enum": ["content", "files"], "description": "Search mode", "default": "content"},
            "file_glob": {"type": "string", "description": "File filter glob (e.g. *.py)"},
        },
        "required": ["pattern"],
    }

    async def execute(self, pattern: str, path: str = ".", target: str = "content", file_glob: str = None, **kw) -> str:
        try:
            p = Path(path).expanduser().resolve()
            results = []
            if target == "files":
                for f in p.rglob(pattern):
                    results.append(str(f))
                    if len(results) >= 50:
                        break
            else:
                regex = re.compile(pattern, re.IGNORECASE)
                glob = file_glob or "*"
                for f in p.rglob(glob):
                    if f.is_file():
                        try:
                            for i, line in enumerate(f.read_text(errors="replace").splitlines(), 1):
                                if regex.search(line):
                                    results.append(f"{f}:{i}: {line.strip()}")
                                    if len(results) >= 50:
                                        break
                        except Exception:
                            pass
                    if len(results) >= 50:
                        break
            if not results:
                return "No matches found."
            return "\n".join(results)
        except Exception as e:
            return f"ERROR: {e}"

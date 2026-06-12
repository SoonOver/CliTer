"""Tool registry — auto-discover and manage tools."""
from cliter.tools.base import BaseTool

_tools: dict[str, BaseTool] = {}

def register(tool: BaseTool):
    _tools[tool.name] = tool

def get(name: str) -> BaseTool | None:
    return _tools.get(name)

def all_tools() -> list[BaseTool]:
    return list(_tools.values())

def all_schemas() -> list[dict]:
    return [t.to_schema() for t in _tools.values()]

def load_defaults():
    """Load built-in tools."""
    from cliter.tools.terminal import TerminalTool
    from cliter.tools.file_ops import ReadFileTool, WriteFileTool, SearchFilesTool, PatchFileTool
    from cliter.tools.web import WebSearchTool
    from cliter.tools.self_improve import SelfImproveTool
    from cliter.tools.python_eval import ExecutePythonTool, FetchUrlTool

    for t in [TerminalTool(), ReadFileTool(), WriteFileTool(), SearchFilesTool(), PatchFileTool(), WebSearchTool(), SelfImproveTool(), ExecutePythonTool(), FetchUrlTool()]:
        register(t)

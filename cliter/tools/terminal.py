"""Terminal tool — run shell commands."""
import asyncio
import subprocess
from cliter.tools.base import BaseTool

class TerminalTool(BaseTool):
    name = "terminal"
    description = "Execute a shell command and return output."
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to run"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 120)", "default": 120},
            "workdir": {"type": "string", "description": "Working directory (optional)"},
        },
        "required": ["command"],
    }

    async def execute(self, command: str, timeout: int = 120, workdir: str = None, **kw) -> str:
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=workdir,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode(errors="replace")
            if len(output) > 10000:
                output = output[:5000] + "\n... (truncated) ...\n" + output[-2000:]
            return f"exit_code: {proc.returncode}\n{output}"
        except asyncio.TimeoutError:
            proc.kill()
            return "ERROR: command timed out"
        except Exception as e:
            return f"ERROR: {e}"

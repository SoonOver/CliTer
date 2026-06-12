"""Python evaluation tool — sandboxed code executor."""
import sys
import io
import httpx
from bs4 import BeautifulSoup
from cliter.tools.base import BaseTool

class ExecutePythonTool(BaseTool):
    name = "execute_python"
    description = "Execute a Python script in a local subprocess and return stdout/stderr."
    parameters = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code block to execute"},
            "timeout": {"type": "integer", "description": "Timeout in seconds (default 30)", "default": 30},
        },
        "required": ["code"],
    }

    async def execute(self, code: str, timeout: int = 30, **kw) -> str:
        try:
            # We run it in a clean environment using sys.executable to ensure virtualenv carries over
            import asyncio
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-c", code,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode(errors="replace")
            return f"exit_code: {proc.returncode}\n{output}"
        except asyncio.TimeoutError:
            proc.kill()
            return "ERROR: python execution timed out"
        except Exception as e:
            return f"ERROR: {e}"

class FetchUrlTool(BaseTool):
    name = "fetch_url"
    description = "Fetch raw contents or clean text of a web page/URL."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "HTTP/HTTPS URL to fetch"},
            "mode": {"type": "string", "enum": ["text", "raw"], "description": "Extract text or get raw HTML", "default": "text"},
        },
        "required": ["url"],
    }

    async def execute(self, url: str, mode: str = "text", **kw) -> str:
        try:
            async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                html = resp.text

            if mode == "raw":
                if len(html) > 20000:
                    html = html[:10000] + "\n... (truncated) ...\n" + html[-5000:]
                return html

            # Clean text extraction using BeautifulSoup
            soup = BeautifulSoup(html, "html.parser")
            # remove scripts/styles
            for script in soup(["script", "style"]):
                script.decompose()
            text = soup.get_text(separator="\n")
            # clean whitespace
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase for line in lines for phrase in line.split("  "))
            text = "\n".join(chunk for chunk in chunks if chunk)
            
            if len(text) > 10000:
                text = text[:8000] + "\n... (truncated) ...\n" + text[-2000:]
            return text
        except Exception as e:
            return f"Fetch error: {e}"

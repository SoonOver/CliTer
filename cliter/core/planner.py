"""Autonomous Planner — multi-step task decomposition and execution.

Takes a high-level goal, breaks it into steps, executes each step
using available tools, and reports results. Designed for OSINT
reconnaissance, bug bounty workflows, and exploit chain assembly.
"""
import json
import time
from cliter.llm import get_provider
from cliter.llm.base import Message
from cliter.tools import registry
from cliter.config import settings

PLANNER_SYSTEM_PROMPT = """You are a task planner for CliTer. Your job:
1. Analyze the user's goal
2. Break it into concrete, sequential steps
3. Execute each step using available tools
4. Report progress and final results

Available tools:
{tools_list}

For each step, output ONLY valid JSON with this structure:
{"step": "step description", "tool": "tool_name", "args": {"arg1": "val1"}, "reason": "why this step"}

When the plan is complete or you need user input, output:
{"step": "done", "result": "summary of what was accomplished"}

If a step fails, try to adapt. Do not repeat the same failed step.
Be concise. Use Indonesian if user asks.
"""


class PlannerError(Exception):
    pass


class Planner:
    """Autonomous multi-step task executor."""

    def __init__(self, on_progress=None):
        self.provider = get_provider()
        self._on_progress = on_progress  # callback(msg)
        self.max_steps = 20

    @property
    def tools(self):
        # Lazy load — registry may not be populated at init time
        return registry.all_tools()

    def on_progress(self, cb):
        self._on_progress = cb

    def _tools_list_text(self) -> str:
        lines = []
        for t in self.tools:
            params = list(t.parameters.get("properties", {}).keys())
            lines.append(f"- {t.name}: {t.description}")
            if params:
                lines.append(f"  args: {', '.join(params)}")
        return "\n".join(lines)

    async def execute(self, goal: str) -> str:
        """Execute a multi-step plan for the given goal."""
        sys_prompt = PLANNER_SYSTEM_PROMPT.format(tools_list=self._tools_list_text())
        messages = [
            Message(role="system", content=sys_prompt),
            Message(role="user", content=goal),
        ]

        step_count = 0
        results_log = []

        while step_count < self.max_steps:
            step_count += 1
            if self._on_progress:
                self._on_progress(f"Step {step_count}/{self.max_steps}...")

            try:
                resp = await self.provider.chat(messages)
            except Exception as e:
                return f"Planner error at step {step_count}: {e}\n\nPartial results:\n" + "\n".join(results_log[-10:])

            content = resp.content.strip()

            # Try to parse JSON from response
            plan = self._extract_json(content)

            if not plan:
                # LLM didn't output JSON — treat response as final
                results_log.append(f"[final] {content}")
                break

            if plan.get("step") == "done":
                results_log.append(f"[done] {plan.get('result', content)}")
                break

            step_desc = plan.get("step", "")
            tool_name = plan.get("tool", "")
            tool_args = plan.get("args", {})
            reason = plan.get("reason", "")

            if self._on_progress:
                self._on_progress(f"  → {step_desc} ({tool_name})")

            if not tool_name:
                results_log.append(f"[error] No tool specified in step: {step_desc}")
                continue

            tool = registry.get(tool_name)
            if not tool:
                results_log.append(f"[error] Tool '{tool_name}' not found")
                continue

            try:
                result = await tool.execute(**tool_args)
                if len(str(result)) > 2000:
                    result = str(result)[:1000] + f"\n... (truncated, {len(str(result))} total chars)"
                results_log.append(f"[ok] {step_desc}: {result[:300]}")
            except Exception as e:
                results_log.append(f"[fail] {step_desc}: {e}")
                # Try to adapt — feed error back to LLM
                error_msg = f"Step '{step_desc}' failed: {e}\nTool: {tool_name}\nArgs: {json.dumps(tool_args)}"
                messages.append(Message(role="user", content=error_msg))
                continue

            # Feed result back to LLM for next step
            msg = f"Step result for '{step_desc}':\n{str(result)[:1500]}"
            messages.append(Message(role="user", content=msg))

        # Compile report
        report_parts = [f"## Planner Result: {goal}", ""]
        for entry in results_log:
            report_parts.append(entry)

        return "\n".join(report_parts)

    def _extract_json(self, text: str) -> dict | None:
        """Extract JSON object from text (handles code blocks)."""
        # Try direct parse
        text = text.strip()
        if text.startswith("{"):
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                pass

        # Try to find JSON in code blocks
        import re
        # ```json ... ``` or ``` ... ```
        for pattern in [r"```json\s*([\s\S]*?)\s*```", r"```\s*([\s\S]*?)\s*```"]:
            m = re.search(pattern, text)
            if m:
                try:
                    return json.loads(m.group(1).strip())
                except json.JSONDecodeError:
                    continue

        # Try to find any {...} block
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass

        return None

"""Agent — main brain. Orchestrates LLM calls, tool execution, context."""
import json
from cliter.llm import get_provider
from cliter.llm.base import Message
from cliter.tools import registry
from cliter.core import memory, session
from cliter.core.history import get_llm_messages
from cliter.config import settings
from cliter.skills.loader import load_skill

class Agent:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.provider = get_provider()
        self._on_token = None  # callback(str) for streaming
        self._on_tool = None   # callback(name, result) for tool use

    def on_token(self, cb):
        self._on_token = cb

    def on_tool(self, cb):
        self._on_tool = cb

    async def _build_system_prompt(self) -> str:
        base = settings.get("agent", "system_prompt", default="You are CliTer, a helpful terminal AI assistant.")
        mem_ctx = await memory.get_context()
        parts = [base]
        if mem_ctx:
            parts.append(mem_ctx)
        
        # Load all skills in ~/.cliter/skills/ to inject improved capabilities
        from cliter.skills.loader import list_skills
        all_skills = list_skills()
        if all_skills:
            parts.append("## Available Skills (Self-Improvements):")
            for s in all_skills:
                parts.append(f"### Skill: {s['name']}\n{s['content']}")
        
        return "\n\n".join(parts)

    async def chat(self, user_input: str) -> str:
        """Process user message, return assistant response."""
        # save user message
        await session.add_message(self.session_id, "user", user_input)

        # build messages
        sys_prompt = await self._build_system_prompt()
        history = await get_llm_messages(self.session_id, limit=settings.get("agent", "max_history", default=50))
        messages = [Message(role="system", content=sys_prompt)] + history

        # tool schemas
        tool_schemas = registry.all_schemas()

        # LLM call loop (may need multiple rounds for tool calls)
        max_rounds = 10
        for _ in range(max_rounds):
            if self._on_token:
                # streaming mode
                full_response = ""
                async for chunk in self.provider.stream(messages, tools=tool_schemas if tool_schemas else None):
                    if chunk.startswith("\n__TOOL_CALLS__"):
                        # tool calls from stream
                        tc_json = chunk[len("\n__TOOL_CALLS__"):]
                        tool_calls = json.loads(tc_json)
                        # process tool calls
                        messages.append(Message(role="assistant", content=full_response, tool_calls=tool_calls))
                        await session.add_message(self.session_id, "assistant", full_response, tool_calls=tool_calls)

                        for tc in tool_calls:
                            fn_name = tc["function"]["name"]
                            try:
                                fn_args = json.loads(tc["function"]["arguments"])
                            except json.JSONDecodeError:
                                fn_args = {}
                            tool = registry.get(fn_name)
                            if tool:
                                if self._on_tool:
                                    self._on_tool(fn_name, "running...")
                                result = await tool.execute(**fn_args)
                                if self._on_tool:
                                    self._on_tool(fn_name, result[:200])
                            else:
                                result = f"Tool '{fn_name}' not found"

                            tool_msg = Message(role="tool", content=result, tool_call_id=tc["id"])
                            messages.append(tool_msg)
                            await session.add_message(self.session_id, "tool", result, tool_call_id=tc["id"])

                        full_response = ""
                        break  # continue outer loop for next LLM round
                    else:
                        full_response += chunk
                        self._on_token(chunk)
                else:
                    # no tool calls, streaming done
                    await session.add_message(self.session_id, "assistant", full_response)
                    return full_response
                continue  # next round after tool calls
            else:
                # non-streaming
                response = await self.provider.chat(messages, tools=tool_schemas if tool_schemas else None)
                if response.tool_calls:
                    messages.append(response)
                    await session.add_message(self.session_id, "assistant", response.content, tool_calls=response.tool_calls)

                    for tc in response.tool_calls:
                        fn_name = tc["function"]["name"]
                        try:
                            fn_args = json.loads(tc["function"]["arguments"])
                        except json.JSONDecodeError:
                            fn_args = {}
                        tool = registry.get(fn_name)
                        if tool:
                            result = await tool.execute(**fn_args)
                        else:
                            result = f"Tool '{fn_name}' not found"
                        tool_msg = Message(role="tool", content=result, tool_call_id=tc["id"])
                        messages.append(tool_msg)
                        await session.add_message(self.session_id, "tool", result, tool_call_id=tc["id"])
                    continue
                else:
                    await session.add_message(self.session_id, "assistant", response.content)
                    return response.content

        return "Max tool rounds reached."

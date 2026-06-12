"""OpenAI-compatible provider. Works with OpenRouter, Ollama, LM Studio, etc."""
import json
import httpx
from typing import AsyncIterator
from cliter.llm.base import BaseLLMProvider, Message
from cliter.config import settings

class OpenAICompatProvider(BaseLLMProvider):
    def __init__(self, override_base_url: str = None, override_api_key: str = None):
        self._override_base_url = override_base_url
        self._override_api_key = override_api_key

    def _headers(self) -> dict:
        key = self._override_api_key or settings.get("llm", "api_key", default="")
        h = {"Content-Type": "application/json"}
        if key:
            h["Authorization"] = f"Bearer {key}"
        return h

    def _base_url(self) -> str:
        if self._override_base_url:
            return self._override_base_url.rstrip("/")
        return settings.get("llm", "base_url", default="https://api.openai.com/v1").rstrip("/")

    def _model(self) -> str:
        return settings.get("llm", "model", default="gpt-4o-mini")

    def _build_body(self, messages: list[Message], tools: list[dict] = None, stream: bool = False) -> dict:
        body = {
            "model": self._model(),
            "messages": [m.to_dict() for m in messages],
            "temperature": settings.get("llm", "temperature", default=0.7),
            "max_tokens": settings.get("llm", "max_tokens", default=4096),
            "stream": stream,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        return body

    async def chat(self, messages: list[Message], tools: list[dict] = None) -> Message:
        body = self._build_body(messages, tools, stream=False)
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{self._base_url()}/chat/completions",
                headers=self._headers(),
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]["message"]
        msg = Message(role="assistant", content=choice.get("content", ""))
        if choice.get("tool_calls"):
            msg.tool_calls = choice["tool_calls"]
        return msg

    async def stream(self, messages: list[Message], tools: list[dict] = None) -> AsyncIterator[str]:
        body = self._build_body(messages, tools, stream=True)
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{self._base_url()}/chat/completions",
                headers=self._headers(),
                json=body,
            ) as resp:
                resp.raise_for_status()
                tool_calls_acc = {}
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk["choices"][0].get("delta", {})
                    if delta.get("content"):
                        yield delta["content"]
                    # accumulate tool calls from stream
                    if delta.get("tool_calls"):
                        for tc in delta["tool_calls"]:
                            idx = tc["index"]
                            if idx not in tool_calls_acc:
                                tool_calls_acc[idx] = {"id": tc.get("id",""), "type": "function", "function": {"name": "", "arguments": ""}}
                            if tc.get("id"):
                                tool_calls_acc[idx]["id"] = tc["id"]
                            fn = tc.get("function", {})
                            if fn.get("name"):
                                tool_calls_acc[idx]["function"]["name"] = fn["name"]
                            if fn.get("arguments"):
                                tool_calls_acc[idx]["function"]["arguments"] += fn["arguments"]
                # yield tool calls as special token
                if tool_calls_acc:
                    yield "\n__TOOL_CALLS__" + json.dumps(list(tool_calls_acc.values()))

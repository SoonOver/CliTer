"""Base LLM provider ABC."""
from abc import ABC, abstractmethod
from typing import AsyncIterator, Any

class Message:
    def __init__(self, role: str, content: str = "", tool_calls: list = None, tool_call_id: str = None, name: str = None):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls or []
        self.tool_call_id = tool_call_id
        self.name = name

    def to_dict(self) -> dict:
        d = {"role": self.role, "content": self.content or ""}
        if self.tool_calls:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d

class BaseLLMProvider(ABC):
    @abstractmethod
    async def chat(self, messages: list[Message], tools: list[dict] = None) -> Message:
        ...

    @abstractmethod
    async def stream(self, messages: list[Message], tools: list[dict] = None) -> AsyncIterator[str]:
        ...

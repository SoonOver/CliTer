"""Base tool ABC."""
from abc import ABC, abstractmethod
from typing import Any

class BaseTool(ABC):
    name: str = ""
    description: str = ""
    parameters: dict = {}  # JSON Schema

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        ...

    def to_schema(self) -> dict:
        """Convert to OpenAI function tool schema."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            }
        }

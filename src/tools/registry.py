from __future__ import annotations

from dataclasses import dataclass, field

from runtime.permissions import PermissionManager
from tools.base import Tool


@dataclass(slots=True)
class ToolRegistry:
    permission_manager: PermissionManager
    tools: dict[str, Tool] = field(default_factory=dict)

    @classmethod
    def default(cls, permission_manager: PermissionManager) -> "ToolRegistry":
        return cls(permission_manager=permission_manager)

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def get_tools(self) -> list[Tool]:
        return list(self.tools.values())

    def find_tool(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def to_model_tool_schemas(self) -> list[dict]:
        schemas: list[dict] = []
        for tool in self.get_tools():
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.input_schema,
                    },
                }
            )
        return schemas

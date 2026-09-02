from __future__ import annotations

import copy
import re
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

try:
    from .log import log_event
except ImportError:
    from log import log_event


MCPHandler = Callable[..., str]

clients_lock = threading.Lock()
mcp_clients: dict[str, "MCPClient"] = {}


@dataclass
class MCPClient:
    name: str
    tools: list[dict[str, Any]] = field(default_factory=list)
    _handlers: dict[str, MCPHandler] = field(default_factory=dict)

    def register(self, tool_defs: list[dict[str, Any]], handlers: dict[str, MCPHandler]) -> None:
        self.tools = copy.deepcopy(tool_defs)
        self._handlers = dict(handlers)
        log_event("MCP", "registered", server=self.name, tools=len(self.tools))

    def list_tools(self) -> list[dict[str, Any]]:
        return copy.deepcopy(self.tools)

    def call_tool(self, name: str, args: dict[str, Any]) -> str:
        handler = self._handlers.get(name)
        if handler is None:
            raise ValueError(f"MCP tool not found on {self.name}: {name}")
        log_event("MCP", "call", server=self.name, tool=name)
        return str(handler(**args))


def connect_mcp(name: str) -> str:
    safe_name = normalize_mcp_name(name)
    client = MCPClient(safe_name)
    tool_defs, handlers = builtin_server(safe_name)
    client.register(tool_defs, handlers)
    with clients_lock:
        mcp_clients[safe_name] = client
    log_event("MCP", "connected", server=safe_name, tools=len(tool_defs))
    exposed = ", ".join(mcp_tool_name(safe_name, tool["name"]) for tool in tool_defs)
    return f"Connected MCP server {safe_name}; discovered {len(tool_defs)} tools: {exposed}"


def disconnect_mcp(name: str) -> str:
    safe_name = normalize_mcp_name(name)
    with clients_lock:
        removed = mcp_clients.pop(safe_name, None)
    if removed is None:
        return f"MCP server {safe_name} is not connected."
    log_event("MCP", "disconnected", server=safe_name)
    return f"Disconnected MCP server {safe_name}."


def assemble_tool_pool(
    builtin_tools: list[dict[str, Any]],
    builtin_handlers: dict[str, Callable[..., str]],
) -> tuple[list[dict[str, Any]], dict[str, Callable[..., str]]]:
    tools = copy.deepcopy(builtin_tools)
    handlers: dict[str, Callable[..., str]] = dict(builtin_handlers)
    with clients_lock:
        clients = list(mcp_clients.values())

    for client in clients:
        server_name = normalize_mcp_name(client.name)
        for tool in client.list_tools():
            original_name = str(tool["name"])
            exposed_name = mcp_tool_name(server_name, original_name)
            exposed = copy.deepcopy(tool)
            exposed["name"] = exposed_name
            exposed["description"] = f"[MCP:{server_name}] {exposed.get('description', '')}".strip()
            if "inputSchema" in exposed and "input_schema" not in exposed:
                exposed["input_schema"] = exposed.pop("inputSchema")
            tools.append(exposed)
            handlers[exposed_name] = (
                lambda *, _client=client, _tool=original_name, **kwargs: _client.call_tool(_tool, kwargs)
            )

    return tools, handlers


def connected_mcp_summary() -> str:
    with clients_lock:
        clients = list(mcp_clients.values())
    if not clients:
        return ""
    lines = ["Connected MCP servers:"]
    for client in clients:
        tool_names = ", ".join(mcp_tool_name(client.name, tool["name"]) for tool in client.list_tools())
        lines.append(f"- {client.name}: {tool_names}")
    return "\n".join(lines)


def normalize_mcp_name(name: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "_", str(name).strip().lower())
    value = value.strip("_-")
    return value or "server"


def mcp_tool_name(server: str, tool: str) -> str:
    return f"mcp__{normalize_mcp_name(server)}__{normalize_mcp_name(tool)}"


def builtin_server(name: str) -> tuple[list[dict[str, Any]], dict[str, MCPHandler]]:
    if name == "docs":
        return docs_server()
    if name == "memory":
        return memory_server()
    return echo_server(name)


def docs_server() -> tuple[list[dict[str, Any]], dict[str, MCPHandler]]:
    tool_defs = [
        {
            "name": "search",
            "description": "Search the teaching docs index.",
            "input_schema": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search query."}},
                "required": ["query"],
            },
        },
        {
            "name": "fetch",
            "description": "Fetch a short teaching note by topic.",
            "input_schema": {
                "type": "object",
                "properties": {"topic": {"type": "string", "description": "Topic id or title."}},
                "required": ["topic"],
            },
        },
    ]
    notes = {
        "agent_loop": "Agent loop = messages -> LLM -> tool calls -> results -> repeat.",
        "mcp": "MCP exposes tools through tools/list and tools/call, decoupling agents from tool implementations.",
        "worktree": "Git worktrees isolate concurrent file edits while sharing one object database.",
    }

    def search(query: str) -> str:
        q = query.lower()
        matches = [key for key, value in notes.items() if q in key.lower() or q in value.lower()]
        return "\n".join(matches) if matches else "(no docs matches)"

    def fetch(topic: str) -> str:
        key = topic.lower().strip()
        return notes.get(key, "(topic not found)")

    return tool_defs, {"search": search, "fetch": fetch}


def memory_server() -> tuple[list[dict[str, Any]], dict[str, MCPHandler]]:
    tool_defs = [
        {
            "name": "remember",
            "description": "Echo a fact as if storing it in an external memory service.",
            "input_schema": {
                "type": "object",
                "properties": {"fact": {"type": "string", "description": "Fact to remember."}},
                "required": ["fact"],
            },
        }
    ]
    return tool_defs, {"remember": lambda fact: f"remembered: {fact}"}


def echo_server(name: str) -> tuple[list[dict[str, Any]], dict[str, MCPHandler]]:
    tool_defs = [
        {
            "name": "echo",
            "description": f"Echo text through the {name} MCP server.",
            "input_schema": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "Text to echo."}},
                "required": ["text"],
            },
        },
        {
            "name": "describe",
            "description": "Describe this mock MCP server.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
    ]
    return tool_defs, {
        "echo": lambda text: text,
        "describe": lambda: f"{name} is a teaching MCP server with in-memory handlers.",
    }

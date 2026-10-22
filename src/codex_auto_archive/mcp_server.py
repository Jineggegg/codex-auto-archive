from __future__ import annotations

import json

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations

from .service import TOOL_DEFS, Service


async def serve(store=None):
    service = Service(store)
    server = Server(
        "codex-auto-archive",
        version="0.1.0",
        instructions="Manage native Codex Archive with exact IDs, independent rules, previews and user confirmation. Never guess current thread or report scheduled/skipped actions as archived. Reply in the user's language. First-install automation is Dry Run. Background work uses no model.",
    )

    @server.list_tools()
    async def list_tools():
        readonly = {
            "get_archive_settings",
            "get_archive_status",
            "list_threads",
            "get_archive_history",
        }
        return [
            Tool(
                name=name,
                description=description,
                inputSchema=model.model_json_schema(),
                annotations=ToolAnnotations(
                    readOnlyHint=name in readonly,
                    destructiveHint=False,
                    idempotentHint=name in readonly,
                    openWorldHint=name == "link_workflow",
                ),
            )
            for name, (model, description) in TOOL_DEFS.items()
        ]

    @server.call_tool(validate_input=True)
    async def call_tool(name, arguments):
        try:
            result = await service.call(name, arguments)
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                structuredContent=result,
            )
        except Exception as e:
            result = {
                "executed": False,
                "affected_count": 0,
                "error": str(e),
                "error_type": type(e).__name__,
            }
            return CallToolResult(
                isError=True,
                content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                structuredContent=result,
            )

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

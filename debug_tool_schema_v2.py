#!/usr/bin/env python3
"""
Alternative debug script to inspect tool schemas.
"""
import json
import sys
import inspect
sys.path.insert(0, '.')

from mcp_calendar_server import mcp

print("=" * 80)
print("INSPECTING MCP SERVER TOOLS")
print("=" * 80)

# Try to access tools through different methods
print(f"\nMCP object type: {type(mcp)}")
print(f"MCP attributes: {[attr for attr in dir(mcp) if not attr.startswith('_')]}")

# Check if tools are stored in a registry
if hasattr(mcp, '_tools'):
    print(f"\nFound _tools: {mcp._tools}")
    for name, tool in mcp._tools.items():
        print(f"\nTool: {name}")
        print(f"  Type: {type(tool)}")
        if hasattr(tool, 'func'):
            sig = inspect.signature(tool.func)
            print(f"  Signature: {sig}")
            for param_name, param in sig.parameters.items():
                print(f"    - {param_name}: {param.annotation} (default: {param.default})")

# Try to get schema via MCP protocol
try:
    import asyncio
    from mcp import types
    
    async def get_schemas():
        # Try to list tools via MCP protocol
        result = await mcp.list_tools()
        if result:
            print(f"\nTools from list_tools(): {result}")
            for tool in result:
                print(f"\nTool: {tool.name}")
                if hasattr(tool, 'inputSchema'):
                    schema = tool.inputSchema
                    print(f"  Schema: {schema}")
    
    # asyncio.run(get_schemas())
except Exception as e:
    print(f"Could not get schemas via MCP protocol: {e}")


from fastmcp import FastMCP

mcp = FastMCP("My MCP TEST Server")

@mcp.tool
def greet(name:str) -> str:
    return f"Hello {name}"

if __name__ == "main":
    mcp.run(transport="http", port=8000)
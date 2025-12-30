# Debugging Guide: n8n MCP Tool Schema Errors

## The Error Explained

The error you're seeing means n8n is receiving tool parameter schemas in a format it doesn't understand:

1. **`date -> type: Expected string. Received list.`**
   - FastMCP is generating `type: ["string", "null"]` (a union type) for `Optional[str]`
   - n8n expects `type: "string"` with the parameter marked as optional via `required: false`

2. **`attendees: Missing required key "type"`**
   - FastMCP isn't generating a proper `type` field for `Optional[list]`
   - n8n requires every parameter to have a `type` field

3. **`body -> type: Expected string. Received list.`**
   - Same issue as #1 - `Optional[str]` is being converted to a union type

## How to Debug

### Step 1: Check What Schema FastMCP is Actually Generating

Start your MCP server and make an HTTP request to see the actual schema:

```bash
# Start your MCP server
python3 mcp_calendar_server.py

# In another terminal, query the tools endpoint
curl http://localhost:8000/mcp/v1/tools | python3 -m json.tool
```

Or use the debug script:
```bash
source mcp-practice/bin/activate
python3 debug_tool_schema.py
```

### Step 2: Check n8n's MCP Connection

In n8n:
1. Go to your MCP server connection settings
2. Check what URL it's connecting to
3. Try manually calling the tools endpoint to see the raw response

### Step 3: Inspect the Actual Schema Format

The issue is likely that FastMCP is using JSON Schema's union types (`type: ["string", "null"]`) which n8n doesn't support. 

## Potential Solutions

### Solution 1: Use Explicit Type Annotations (Recommended)

Instead of `Optional[str]`, try using `str | None` with explicit handling, or remove the Optional and handle None in the function:

```python
@mcp.tool()
def check_availability(user_email: str, date: str = "") -> dict:
    """date: The date to check in YYYY-MM-DD format. Leave empty for today."""
    if not date or date == "":
        date = datetime.now().strftime("%Y-%m-%d")
    # ... rest of function
```

### Solution 2: Use Default Empty Values

Instead of `Optional[list]`, use an empty list as default:

```python
@mcp.tool()
def book_meeting(
    user_email: str,
    subject: str,
    start_datetime: str,
    end_datetime: str,
    sender: str,
    attendees: list = None,  # Use None, not Optional
    body: str = None
) -> dict:
```

### Solution 3: Check FastMCP Version

Your FastMCP version might have a bug. Check:
```bash
pip show fastmcp
```

Consider updating or downgrading if needed.

### Solution 4: Use Custom Schema Transformation

FastMCP might support schema transformations. Check if you can add a transformation to fix the schema format.

## What to Check Next

1. **What does the actual HTTP response look like?**
   - Query `http://localhost:8000/mcp/v1/tools` and inspect the JSON
   - Look for the `inputSchema` field in each tool

2. **What version of FastMCP are you using?**
   - Check `requirements.txt` or run `pip show fastmcp`

3. **What does n8n expect?**
   - Check n8n's documentation for MCP tool schema format
   - The schema might need to follow a specific format

4. **Try removing Optional types temporarily**
   - Make all parameters required and see if the error goes away
   - This will confirm the issue is with Optional type handling

## Quick Test

Try this minimal test to see if the issue reproduces:

```python
@mcp.tool()
def test_optional(required: str, optional: str = "") -> dict:
    """Test function with optional parameter"""
    return {"result": "ok"}

@mcp.tool()
def test_list(required: str, items: list = None) -> dict:
    """Test function with optional list"""
    return {"result": "ok"}
```

Then check what schema FastMCP generates for these.


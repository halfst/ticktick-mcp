"""MCP server / tool layer.

DESIGN.md law: this layer is thin. Tools validate/shape inputs, call a typed
client method, and return a clean result. A tool NEVER touches a raw endpoint or
payload — it only calls ``ticktick_mcp.client`` methods.

Slice 3 fills in the FastMCP tool definitions.
"""

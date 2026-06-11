"""v2 API client layer.

DESIGN.md law: every TickTick v2 endpoint URL and raw payload shape lives ONLY
in this package. Nothing outside ``ticktick_mcp.client`` may construct a raw
request or know an endpoint path.

Slice 1 fills in auth + transport; Slice 2 fills in the typed endpoint methods.
"""

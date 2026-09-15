# Composer

The design MCP — any AI agent calls it to produce on-brand, enterprise-grade design output
(palettes, type systems, components, full page compositions) instead of guessing at CSS.

Not yet deployed. See [`docs/SPEC.md`](docs/SPEC.md) for the full product spec, tool surface,
architecture, and build plan.

## Scaffold

`server/composer_mcp.py` is a minimal proof-of-shape stdio MCP server with two working tools
(`palette`, `brand_guidelines`), self-contained generation logic, no external dependencies.

```bash
python3 server/composer_mcp.py
```

Speaks MCP over stdio (JSON-RPC 2.0, newline-delimited). See SPEC.md Phase 1 for wiring this to
the (currently broken) `axe-design-system` corpus instead of the placeholder logic here.

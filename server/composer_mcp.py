#!/usr/bin/env python3
"""Composer MCP server (stdio) — minimal proof-of-shape scaffold.

Implements two tools end to end with self-contained generation logic
(no external corpus dependency yet — see docs/SPEC.md Phase 1 for
wiring this to a repaired axe-design-system corpus):

  - palette:            generate an on-brand color palette
  - brand_guidelines:   generate a brand guidelines document

Not deployed. Run locally with: python3 composer_mcp.py
Speaks MCP over stdio (JSON-RPC 2.0, newline-delimited).
"""

import colorsys
import json
import sys


def _hsl_to_hex(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h / 360.0, l, s)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def _relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    rgb = [int(hex_color[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast_ratio(fg: str, bg: str) -> float:
    l1, l2 = _relative_luminance(fg), _relative_luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return round((lighter + 0.05) / (darker + 0.05), 2)


# Deterministic hue picks per rough context keyword — placeholder logic
# standing in for the real axe-design-system BM25 corpus (see SPEC.md).
_CONTEXT_HUES = {
    "fintech": 215,
    "healthcare": 165,
    "dashboard": 230,
    "ecommerce": 20,
    "editorial": 15,
    "developer": 260,
}


def _pick_base_hue(context: str) -> float:
    context_lower = context.lower()
    for keyword, hue in _CONTEXT_HUES.items():
        if keyword in context_lower:
            return hue
    # stable fallback derived from string hash, not random, so repeat calls
    # with the same context return the same palette
    return sum(context_lower.encode()) % 360


def _build_palette(context: str, mode: str, seed_color: str | None) -> dict:
    base_hue = _pick_base_hue(context)
    dark = mode in ("dark", "both")

    if seed_color:
        primary = seed_color
    else:
        primary = _hsl_to_hex(base_hue, 0.55, 0.50)

    roles = {
        "primary": primary,
        "secondary": _hsl_to_hex((base_hue + 30) % 360, 0.45, 0.55),
        "accent": _hsl_to_hex((base_hue + 150) % 360, 0.65, 0.55),
        "background": _hsl_to_hex(base_hue, 0.15, 0.08) if dark else _hsl_to_hex(base_hue, 0.20, 0.98),
        "surface": _hsl_to_hex(base_hue, 0.12, 0.12) if dark else _hsl_to_hex(base_hue, 0.10, 1.00),
        "text": _hsl_to_hex(base_hue, 0.05, 0.95) if dark else _hsl_to_hex(base_hue, 0.20, 0.10),
        "border": _hsl_to_hex(base_hue, 0.15, 0.22) if dark else _hsl_to_hex(base_hue, 0.15, 0.88),
    }

    contrast_report = {
        "text_on_background": _contrast_ratio(roles["text"], roles["background"]),
        "text_on_surface": _contrast_ratio(roles["text"], roles["surface"]),
        "primary_on_background": _contrast_ratio(roles["primary"], roles["background"]),
    }
    for pair, ratio in contrast_report.items():
        contrast_report[pair] = {"ratio": ratio, "wcag_aa": ratio >= 4.5, "wcag_aaa": ratio >= 7.0}

    return {
        "name": f"{context.strip().title()} — {'dark' if dark else 'light'}",
        "roles": roles,
        "contrast_report": contrast_report,
    }


def tool_palette(args: dict) -> dict:
    context = args["context"]
    mode = args.get("mode", "both")
    count = args.get("count", 3)
    seed_color = args.get("seed_color")

    modes = ["light", "dark"] if mode == "both" else [mode]
    palettes = []
    for m in modes:
        for i in range(max(1, count // len(modes))):
            variant_context = context if i == 0 else f"{context} variant {i}"
            palettes.append(_build_palette(variant_context, m, seed_color))
    return {"palettes": palettes[:count] if count else palettes}


def tool_brand_guidelines(args: dict) -> dict:
    product_description = args["product_description"]
    tone = args.get("tone", "utilitarian")
    palette = _build_palette(product_description, "both", None)

    type_pairs = {
        "editorial": ("Fraunces", "Source Serif Pro"),
        "utilitarian": ("Inter", "IBM Plex Mono"),
        "playful": ("Poppins", "Nunito"),
        "technical": ("JetBrains Mono", "Inter"),
    }
    heading_font, body_font = type_pairs.get(tone, type_pairs["utilitarian"])

    markdown = f"""# Brand Guidelines — {product_description.strip().title()}

## Tone
{tone.title()} — {"warm, narrative, generous whitespace" if tone == "editorial" else "clean, dense, functional"}.

## Palette
| Role | Hex |
|---|---|
""" + "\n".join(f"| {role} | `{hex_val}` |" for role, hex_val in palette["roles"].items()) + f"""

## Typography
- Heading: **{heading_font}**
- Body: **{body_font}**

## Do
- Keep contrast at or above WCAG AA (4.5:1) for all body text.
- Use the accent color sparingly — calls to action only.

## Don't
- Don't introduce a second accent color without a documented reason.
- Don't set body text below 14px.
"""

    tokens = {
        "color": palette["roles"],
        "type": {"heading_font": heading_font, "body_font": body_font},
        "spacing": {"scale": [4, 8, 12, 16, 24, 32, 48, 64]},
    }

    return {"markdown": markdown, "tokens": tokens}


TOOLS = {
    "palette": {
        "description": "Generate a WCAG-aware color palette for a product context, or validate a supplied brand color against one.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "context": {"type": "string", "description": "Product/brand context, e.g. 'fintech dark dashboard'"},
                "seed_color": {"type": "string", "description": "Optional hex to anchor the palette to an existing brand color"},
                "mode": {"type": "string", "enum": ["light", "dark", "both"], "default": "both"},
                "count": {"type": "integer", "default": 3, "description": "Number of palette options to return"},
            },
            "required": ["context"],
        },
        "handler": tool_palette,
    },
    "brand_guidelines": {
        "description": "Generate a brand guidelines document (voice, palette, typography, spacing, do/don't rules) from a product description.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "product_description": {"type": "string"},
                "tone": {"type": "string", "enum": ["editorial", "utilitarian", "playful", "technical"], "default": "utilitarian"},
            },
            "required": ["product_description"],
        },
        "handler": tool_brand_guidelines,
    },
}


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _handle_request(req: dict) -> dict | None:
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "composer-mcp", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            },
        }

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {"name": name, "description": spec["description"], "inputSchema": spec["inputSchema"]}
                    for name, spec in TOOLS.items()
                ]
            },
        }

    if method == "tools/call":
        params = req.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"unknown tool: {name}"}}
        try:
            result = TOOLS[name]["handler"](args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]},
            }
        except Exception as exc:  # noqa: BLE001 — surface any generation error to the caller
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(exc)}}

    if req_id is None:
        return None  # notification, no response expected

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"unknown method: {method}"}}


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = _handle_request(req)
        if resp is not None:
            _send(resp)


if __name__ == "__main__":
    main()

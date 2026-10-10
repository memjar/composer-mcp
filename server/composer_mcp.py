#!/usr/bin/env python3
"""Composer MCP server (stdio) — design system MCP for all things design.

8 tools:
  palette, brand_guidelines, generate_design_system, create_component,
  compose_page, export, render_visual, design_critique

Speaks MCP over stdio (JSON-RPC 2.0, newline-delimited).
Optional aivision bridge for image rendering (AIVISION_URL env var).
"""

import base64
import colorsys
import json
import os
import sys
import textwrap
from pathlib import Path

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

AIVISION_URL = os.environ.get("AIVISION_URL", "http://127.0.0.1:7790")
COMPOSE_HOST = os.environ.get("COMPOSE_HOST", "")


def _hsl_to_hex(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h / 360.0, l, s)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    rgb = [int(hex_color[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast_ratio(fg: str, bg: str) -> float:
    l1, l2 = _relative_luminance(fg), _relative_luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return round((lighter + 0.05) / (darker + 0.05), 2)


_CONTEXT_HUES = {
    "fintech": 215, "healthcare": 165, "dashboard": 230,
    "ecommerce": 20, "editorial": 15, "developer": 260,
    "saas": 225, "social": 200, "gaming": 280, "education": 145,
}


def _pick_base_hue(context: str) -> float:
    cl = context.lower()
    for keyword, hue in _CONTEXT_HUES.items():
        if keyword in cl:
            return hue
    return sum(cl.encode()) % 360


def _build_palette(context: str, mode: str, seed_color: str | None) -> dict:
    base_hue = _pick_base_hue(context)
    dark = mode in ("dark", "both")
    primary = seed_color if seed_color else _hsl_to_hex(base_hue, 0.55, 0.50)
    roles = {
        "primary": primary,
        "secondary": _hsl_to_hex((base_hue + 30) % 360, 0.45, 0.55),
        "accent": _hsl_to_hex((base_hue + 150) % 360, 0.65, 0.55),
        "background": _hsl_to_hex(base_hue, 0.15, 0.08) if dark else _hsl_to_hex(base_hue, 0.20, 0.98),
        "surface": _hsl_to_hex(base_hue, 0.12, 0.12) if dark else _hsl_to_hex(base_hue, 0.10, 1.00),
        "text": _hsl_to_hex(base_hue, 0.05, 0.95) if dark else _hsl_to_hex(base_hue, 0.20, 0.10),
        "border": _hsl_to_hex(base_hue, 0.15, 0.22) if dark else _hsl_to_hex(base_hue, 0.15, 0.88),
        "success": "#22c55e", "warning": "#f59e0b", "error": "#ef4444", "info": _hsl_to_hex(base_hue, 0.50, 0.55),
    }
    contrast_report = {}
    for pair_name, (fg, bg) in [("text_on_background", ("text", "background")), ("text_on_surface", ("text", "surface")), ("primary_on_background", ("primary", "background"))]:
        ratio = _contrast_ratio(roles[fg], roles[bg])
        contrast_report[pair_name] = {"ratio": ratio, "wcag_aa": ratio >= 4.5, "wcag_aaa": ratio >= 7.0}
    return {"name": f"{context.strip().title()} — {'dark' if dark else 'light'}", "roles": roles, "contrast_report": contrast_report}


_TYPE_PAIRS = {
    "editorial": ("Fraunces", "Source Serif Pro", 1.6),
    "utilitarian": ("Inter", "IBM Plex Mono", 1.5),
    "playful": ("Poppins", "Nunito", 1.6),
    "technical": ("JetBrains Mono", "Inter", 1.4),
}

_SPACING_SCALE = [2, 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96, 128]

_TYPE_SCALE = {
    "xs": 12, "sm": 14, "base": 16, "lg": 18, "xl": 20,
    "2xl": 24, "3xl": 30, "4xl": 36, "5xl": 48, "6xl": 60,
}

_COMPONENT_SPECS = {
    "button": {
        "variants": ["primary", "secondary", "outline", "ghost", "destructive"],
        "sizes": {"sm": {"px": 12, "py": 6, "font": 14}, "md": {"px": 16, "py": 10, "font": 16}, "lg": {"px": 24, "py": 14, "font": 18}},
        "states": ["default", "hover", "active", "focus", "disabled"],
        "radius": 8,
    },
    "card": {
        "variants": ["elevated", "outlined", "filled"],
        "sizes": {"sm": {"p": 16}, "md": {"p": 24}, "lg": {"p": 32}},
        "states": ["default", "hover", "selected"],
        "radius": 12,
    },
    "input": {
        "variants": ["outlined", "filled", "underlined"],
        "sizes": {"sm": {"px": 12, "py": 8, "font": 14}, "md": {"px": 16, "py": 12, "font": 16}, "lg": {"px": 20, "py": 16, "font": 18}},
        "states": ["default", "focus", "error", "disabled"],
        "radius": 8,
    },
    "badge": {
        "variants": ["solid", "outline", "soft"],
        "sizes": {"sm": {"px": 6, "py": 2, "font": 11}, "md": {"px": 8, "py": 4, "font": 12}},
        "states": ["default"],
        "radius": 9999,
    },
    "modal": {
        "variants": ["centered", "slideout"],
        "sizes": {"sm": {"w": 400}, "md": {"w": 560}, "lg": {"w": 720}, "full": {"w": "100%"}},
        "states": ["open", "closing"],
        "radius": 16,
    },
    "nav": {
        "variants": ["horizontal", "vertical", "sidebar"],
        "sizes": {"compact": {"h": 48}, "default": {"h": 64}},
        "states": ["default", "collapsed"],
        "radius": 0,
    },
    "table": {
        "variants": ["striped", "bordered", "minimal"],
        "sizes": {"compact": {"cell_py": 8}, "default": {"cell_py": 12}, "spacious": {"cell_py": 16}},
        "states": ["default", "loading", "empty"],
        "radius": 8,
    },
    "avatar": {
        "variants": ["circle", "rounded", "square"],
        "sizes": {"xs": {"wh": 24}, "sm": {"wh": 32}, "md": {"wh": 40}, "lg": {"wh": 56}, "xl": {"wh": 80}},
        "states": ["default", "loading"],
        "radius": 9999,
    },
    "toast": {
        "variants": ["info", "success", "warning", "error"],
        "sizes": {"default": {"w": 360, "p": 16}},
        "states": ["entering", "visible", "exiting"],
        "radius": 8,
    },
    "tabs": {
        "variants": ["underline", "pill", "enclosed"],
        "sizes": {"sm": {"py": 8, "font": 14}, "md": {"py": 12, "font": 16}},
        "states": ["default", "active", "disabled"],
        "radius": 8,
    },
}

_LAYOUT_PATTERNS = {
    "hero": '<section style="padding:80px 40px;text-align:center;background:{bg};color:{text}"><h1 style="font-family:{heading};font-size:48px;margin-bottom:16px">{title}</h1><p style="font-size:20px;max-width:640px;margin:0 auto 32px;opacity:0.8">{subtitle}</p><a href="#" style="display:inline-block;padding:14px 32px;background:{primary};color:#fff;border-radius:8px;text-decoration:none;font-weight:600">{cta}</a></section>',
    "feature_grid": '<section style="padding:64px 40px;background:{surface}"><div style="display:grid;grid-template-columns:repeat(3,1fr);gap:24px;max-width:1200px;margin:0 auto">{features}</div></section>',
    "sidebar_layout": '<div style="display:flex;min-height:100vh"><aside style="width:260px;background:{surface};border-right:1px solid {border};padding:24px"><nav>{nav_items}</nav></aside><main style="flex:1;padding:32px;background:{bg};color:{text}">{main_content}</main></div>',
    "pricing_table": '<section style="padding:64px 40px;background:{bg};color:{text};text-align:center"><h2 style="font-family:{heading};font-size:36px;margin-bottom:48px">{title}</h2><div style="display:flex;gap:24px;justify-content:center;flex-wrap:wrap">{plans}</div></section>',
    "dashboard": '<div style="display:grid;grid-template-columns:260px 1fr;grid-template-rows:64px 1fr;min-height:100vh"><header style="grid-column:1/-1;background:{surface};border-bottom:1px solid {border};display:flex;align-items:center;padding:0 24px;color:{text};font-family:{heading}">{header}</header><aside style="background:{surface};border-right:1px solid {border};padding:16px">{sidebar}</aside><main style="padding:24px;background:{bg};color:{text}">{main_content}</main></div>',
    "footer": '<footer style="padding:48px 40px;background:{surface};color:{text};border-top:1px solid {border}"><div style="display:flex;justify-content:space-between;max-width:1200px;margin:0 auto">{columns}</div></footer>',
}


def _aivision_post(path: str, body: dict) -> dict | None:
    if not HAS_HTTPX:
        return None
    try:
        key = os.environ.get("AXE_FLEET_KEY", "")
        headers = {"Content-Type": "application/json"}
        if key:
            headers["x-axe-key"] = key
        resp = httpx.post(f"{AIVISION_URL}{path}", json=body, headers=headers, timeout=15.0)
        return resp.json()
    except Exception:
        return None


def _tokens_to_css(tokens: dict) -> str:
    lines = [":root {"]
    for role, val in tokens.get("color", {}).items():
        lines.append(f"  --color-{role}: {val};")
    for name, px in tokens.get("type_scale", _TYPE_SCALE).items():
        lines.append(f"  --font-{name}: {px}px;")
    for i, s in enumerate(tokens.get("spacing", _SPACING_SCALE)):
        lines.append(f"  --space-{i}: {s}px;")
    if tokens.get("heading_font"):
        lines.append(f"  --font-heading: '{tokens['heading_font']}', sans-serif;")
    if tokens.get("body_font"):
        lines.append(f"  --font-body: '{tokens['body_font']}', sans-serif;")
    lines.append("}")
    return "\n".join(lines)


# ── Tool: palette ──

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
    result = {"palettes": palettes[:count] if count else palettes}
    swatch = _aivision_post("/generate", {"type": "palette", "colors": [list(_hex_to_rgb(p["roles"]["primary"])) for p in result["palettes"]]})
    if swatch and swatch.get("image_b64"):
        result["swatch_b64"] = swatch["image_b64"]
    return result


# ── Tool: brand_guidelines ──

def tool_brand_guidelines(args: dict) -> dict:
    product_description = args["product_description"]
    tone = args.get("tone", "utilitarian")
    palette = _build_palette(product_description, "both", None)
    heading_font, body_font, line_height = _TYPE_PAIRS.get(tone, _TYPE_PAIRS["utilitarian"])
    markdown = f"""# Brand Guidelines — {product_description.strip().title()}

## Tone
{tone.title()} — {"warm, narrative, generous whitespace" if tone == "editorial" else "clean, dense, functional" if tone == "utilitarian" else "friendly, rounded, approachable" if tone == "playful" else "precise, monospaced, minimal"}.

## Palette
| Role | Hex |
|---|---|
""" + "\n".join(f"| {role} | `{hex_val}` |" for role, hex_val in palette["roles"].items()) + f"""

## Typography
- Heading: **{heading_font}** / line-height {line_height}
- Body: **{body_font}** / line-height {line_height + 0.1}
- Scale: {', '.join(f'{k}={v}px' for k, v in _TYPE_SCALE.items())}

## Spacing
Scale (px): {', '.join(str(s) for s in _SPACING_SCALE)}

## Do
- Keep contrast at or above WCAG AA (4.5:1) for all body text.
- Use the accent color sparingly — calls to action only.
- Maintain consistent spacing from the scale — never ad-hoc pixel values.

## Don't
- Don't introduce a second accent color without a documented reason.
- Don't set body text below 14px.
- Don't mix type families outside the heading/body pair.
"""
    tokens = {"color": palette["roles"], "type": {"heading_font": heading_font, "body_font": body_font}, "spacing": {"scale": _SPACING_SCALE}}
    return {"markdown": markdown, "tokens": tokens}


# ── Tool: generate_design_system ──

def tool_generate_design_system(args: dict) -> dict:
    query = args["query"]
    treatment = args.get("treatment", "utilitarian")
    theme_aware = args.get("theme_aware", True)

    heading_font, body_font, line_height = _TYPE_PAIRS.get(treatment, _TYPE_PAIRS["utilitarian"])

    palettes = {}
    if theme_aware:
        palettes["light"] = _build_palette(query, "light", args.get("seed_color"))
        palettes["dark"] = _build_palette(query, "dark", args.get("seed_color"))
    else:
        palettes["default"] = _build_palette(query, "light", args.get("seed_color"))

    typography = {
        "heading_font": heading_font, "body_font": body_font,
        "line_height": line_height, "scale": _TYPE_SCALE,
        "weights": {"normal": 400, "medium": 500, "semibold": 600, "bold": 700},
    }

    components = []
    for name, spec in _COMPONENT_SPECS.items():
        components.append({"name": name, **spec})

    accessibility = [
        {"rule": "color-contrast", "level": "AA", "description": "All text must meet 4.5:1 contrast ratio against its background"},
        {"rule": "focus-visible", "description": "All interactive elements must have a visible focus indicator using the primary color with 2px offset"},
        {"rule": "motion-reduced", "description": "Honor prefers-reduced-motion; disable transitions and animations"},
        {"rule": "touch-target", "description": "Minimum 44x44px touch targets for mobile"},
        {"rule": "aria-labels", "description": "All icon-only buttons require aria-label"},
    ]

    first_palette = list(palettes.values())[0]
    tokens = {**first_palette["roles"], "heading_font": heading_font, "body_font": body_font, "type_scale": _TYPE_SCALE, "spacing": _SPACING_SCALE}
    tokens_css = _tokens_to_css(tokens)

    return {
        "design_system": {
            "palette": palettes,
            "typography": typography,
            "spacing": {"scale": _SPACING_SCALE, "unit": "px"},
            "border_radius": {"sm": 4, "md": 8, "lg": 12, "xl": 16, "full": 9999},
            "shadows": {
                "sm": "0 1px 2px rgba(0,0,0,0.06)",
                "md": "0 4px 6px rgba(0,0,0,0.07)",
                "lg": "0 10px 15px rgba(0,0,0,0.1)",
                "xl": "0 20px 25px rgba(0,0,0,0.15)",
            },
            "components": components,
            "accessibility": accessibility,
        },
        "tokens_css": tokens_css,
    }


# ── Tool: create_component ──

def _component_html(name: str, spec: dict, tokens: dict) -> str:
    p = tokens or {}
    primary = p.get("primary", "#3b82f6")
    bg = p.get("background", "#ffffff")
    text = p.get("text", "#111111")
    border = p.get("border", "#e5e7eb")
    surface = p.get("surface", "#f9fafb")
    radius = spec.get("radius", 8)

    if name == "button":
        return f'<button style="padding:10px 16px;background:{primary};color:#fff;border:none;border-radius:{radius}px;font-size:16px;cursor:pointer;font-weight:600;transition:opacity 0.15s" onmouseover="this.style.opacity=0.9" onmouseout="this.style.opacity=1">Button</button>'
    if name == "card":
        return f'<div style="background:{surface};border:1px solid {border};border-radius:{radius}px;padding:24px;color:{text}"><h3 style="margin:0 0 8px">Card Title</h3><p style="margin:0;opacity:0.7">Card description text goes here.</p></div>'
    if name == "input":
        return f'<div><label style="display:block;margin-bottom:4px;font-size:14px;font-weight:500;color:{text}">Label</label><input type="text" placeholder="Placeholder" style="width:100%;padding:12px 16px;border:1px solid {border};border-radius:{radius}px;font-size:16px;background:{bg};color:{text};outline:none;box-sizing:border-box" onfocus="this.style.borderColor=\'{primary}\'" onblur="this.style.borderColor=\'{border}\'"></div>'
    if name == "badge":
        return f'<span style="display:inline-block;padding:4px 8px;background:{primary};color:#fff;border-radius:{radius}px;font-size:12px;font-weight:600">Badge</span>'
    if name == "toast":
        return f'<div style="padding:16px;background:{surface};border:1px solid {border};border-left:4px solid {primary};border-radius:{radius}px;color:{text};display:flex;align-items:center;gap:12px;max-width:360px"><span style="font-weight:500">Notification message</span></div>'
    if name == "avatar":
        return f'<div style="width:40px;height:40px;border-radius:{radius}px;background:{primary};color:#fff;display:flex;align-items:center;justify-content:center;font-weight:600;font-size:16px">JD</div>'
    return f'<div style="padding:16px;border:1px solid {border};border-radius:{radius}px;color:{text};background:{surface}"><!-- {name} component --></div>'


def _component_react(name: str, spec: dict, tokens: dict) -> str:
    p = tokens or {}
    radius = spec.get("radius", 8)
    if name == "button":
        return textwrap.dedent(f"""\
        export function Button({{ children, variant = "primary", size = "md", ...props }}) {{
          return (
            <button
              className={{`px-4 py-2.5 rounded-lg font-semibold text-white bg-[{p.get('primary','#3b82f6')}] hover:opacity-90 transition-opacity ${{variant === "outline" ? "bg-transparent border border-current" : ""}} ${{size === "sm" ? "px-3 py-1.5 text-sm" : size === "lg" ? "px-6 py-3.5 text-lg" : ""}}`}}
              {{...props}}
            >
              {{children}}
            </button>
          );
        }}""")
    return f"// {name} component — apply tokens via Tailwind config"


def tool_create_component(args: dict) -> dict:
    raw = args["component"].lower().replace("-", " ").replace("_", " ")
    matched = None
    for key in _COMPONENT_SPECS:
        if key in raw:
            matched = key
            break
    if not matched:
        matched = min(_COMPONENT_SPECS.keys(), key=lambda k: abs(len(k) - len(raw)))

    spec = _COMPONENT_SPECS[matched]
    tokens = args.get("tokens", {})
    framework = args.get("framework", "html-css")

    markup = _component_react(matched, spec, tokens) if framework == "react-tailwind" else _component_html(matched, spec, tokens)

    return {"component": matched, "spec": spec, "markup": markup, "framework": framework}


# ── Tool: compose_page ──

def tool_compose_page(args: dict) -> dict:
    pattern = args["pattern"].lower().replace("-", "_").replace(" ", "_")
    tokens = args.get("tokens", {})
    content = args.get("content", {})

    heading_font = tokens.get("heading_font", "Inter")
    t = {
        "bg": tokens.get("background", "#ffffff"),
        "surface": tokens.get("surface", "#f9fafb"),
        "text": tokens.get("text", "#111111"),
        "primary": tokens.get("primary", "#3b82f6"),
        "border": tokens.get("border", "#e5e7eb"),
        "heading": heading_font,
        "title": content.get("title", "Title"),
        "subtitle": content.get("subtitle", "Subtitle text goes here"),
        "cta": content.get("cta", "Get Started"),
        "header": content.get("header", f"<strong>{content.get('title', 'App')}</strong>"),
        "sidebar": content.get("sidebar", "<ul><li>Nav 1</li><li>Nav 2</li><li>Nav 3</li></ul>"),
        "main_content": content.get("main_content", "<h2>Content</h2><p>Main content area.</p>"),
        "nav_items": content.get("nav_items", "<a href='#'>Home</a><br><a href='#'>Settings</a>"),
        "features": content.get("features", "".join(f'<div style="padding:24px;background:{tokens.get("background","#fff")};border:1px solid {tokens.get("border","#e5e7eb")};border-radius:12px"><h3>Feature {i+1}</h3><p>Description</p></div>' for i in range(3))),
        "plans": content.get("plans", ""),
        "columns": content.get("columns", "<div>Footer content</div>"),
    }

    matched = None
    for key in _LAYOUT_PATTERNS:
        if key in pattern:
            matched = key
            break
    if not matched:
        matched = list(_LAYOUT_PATTERNS.keys())[0]

    body_html = _LAYOUT_PATTERNS[matched].format(**t)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{content.get('title', 'Page')}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family={heading_font.replace(' ','+')}:wght@400;600;700&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:'{tokens.get("body_font","Inter")}',sans-serif;background:{t['bg']};color:{t['text']}}}
a{{color:{t['primary']};text-decoration:none}}
</style>
</head>
<body>
{body_html}
</body>
</html>"""

    return {"html": html, "pattern": matched, "notes": f"Layout: {matched}, font: {heading_font}"}


# ── Tool: export ──

def tool_export(args: dict) -> dict:
    content = args["content"]
    content_type = args["content_type"]
    target = args.get("target", "file")
    title = args.get("title", "composer-output")

    ext = {"html": ".html", "css": ".css", "svg": ".svg", "markdown": ".md", "json": ".json"}.get(content_type, ".txt")

    if target == "file":
        out_dir = Path.home() / ".composer" / "exports"
        out_dir.mkdir(parents=True, exist_ok=True)
        slug = title.lower().replace(" ", "-")[:40]
        path = out_dir / f"{slug}{ext}"
        path.write_text(content)
        return {"path": str(path), "size": len(content)}

    if target == "compose_host" and COMPOSE_HOST and HAS_HTTPX:
        try:
            resp = httpx.post(f"{COMPOSE_HOST}/api/create", json={"title": title, "content": content, "type": content_type}, timeout=10.0)
            data = resp.json()
            return {"url": data.get("url", data.get("id", "unknown")), "host": COMPOSE_HOST}
        except Exception as e:
            return {"error": f"compose host unreachable: {e}"}

    return {"error": "compose_host not configured" if target == "compose_host" else "unknown target"}


# ── Tool: render_visual (aivision bridge) ──

def tool_render_visual(args: dict) -> dict:
    visual_type = args.get("type", "badge")
    save_path = args.get("save_path")
    body = {k: v for k, v in args.items() if k != "save_path"}

    if visual_type == "palette_swatch":
        body["type"] = "palette"

    result = _aivision_post("/generate", body)
    if not result:
        return {"error": f"aivision unreachable at {AIVISION_URL}"}
    if result.get("error"):
        return result

    if save_path and result.get("image_b64"):
        Path(save_path).parent.mkdir(parents=True, exist_ok=True)
        Path(save_path).write_bytes(base64.b64decode(result["image_b64"]))
        result["saved_to"] = save_path

    return result


# ── Tool: design_critique ──

def tool_design_critique(args: dict) -> dict:
    tokens = args.get("tokens", {})
    issues = []

    if tokens.get("text") and tokens.get("background"):
        ratio = _contrast_ratio(tokens["text"], tokens["background"])
        if ratio < 4.5:
            issues.append({"severity": "error", "rule": "contrast", "detail": f"text/background contrast {ratio}:1 fails WCAG AA (need 4.5:1)", "fix": "Darken text or lighten background"})
        elif ratio < 7.0:
            issues.append({"severity": "warning", "rule": "contrast", "detail": f"text/background contrast {ratio}:1 passes AA but fails AAA (need 7.0:1)"})

    if tokens.get("primary") and tokens.get("background"):
        ratio = _contrast_ratio(tokens["primary"], tokens["background"])
        if ratio < 3.0:
            issues.append({"severity": "error", "rule": "contrast", "detail": f"primary/background contrast {ratio}:1 too low for UI elements (need 3:1)"})

    spacing = tokens.get("spacing", [])
    if spacing and isinstance(spacing, list):
        for i in range(1, len(spacing)):
            if spacing[i] <= spacing[i-1]:
                issues.append({"severity": "error", "rule": "spacing-scale", "detail": f"Spacing scale not monotonically increasing at index {i}"})
                break

    if not issues:
        issues.append({"severity": "pass", "rule": "all", "detail": "No issues found — tokens pass basic design quality checks"})

    return {"issues": issues, "score": "pass" if all(i["severity"] != "error" for i in issues) else "fail"}


# ── MCP Tool Registry ──

TOOLS = {
    "palette": {
        "description": "Generate a WCAG-aware color palette for a product context, or validate a supplied brand color against one.",
        "inputSchema": {"type": "object", "properties": {"context": {"type": "string", "description": "Product/brand context, e.g. 'fintech dark dashboard'"}, "seed_color": {"type": "string"}, "mode": {"type": "string", "enum": ["light", "dark", "both"], "default": "both"}, "count": {"type": "integer", "default": 3}}, "required": ["context"]},
        "handler": tool_palette,
    },
    "brand_guidelines": {
        "description": "Generate a brand guidelines document (voice, palette, typography, spacing, do/don't rules) from a product description.",
        "inputSchema": {"type": "object", "properties": {"product_description": {"type": "string"}, "tone": {"type": "string", "enum": ["editorial", "utilitarian", "playful", "technical"], "default": "utilitarian"}}, "required": ["product_description"]},
        "handler": tool_brand_guidelines,
    },
    "generate_design_system": {
        "description": "Generate a complete design system (palette, type scale, spacing, component specs, accessibility rules, CSS tokens) for a product context.",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "description": "Product description, e.g. 'enterprise SaaS analytics dashboard'"}, "treatment": {"type": "string", "enum": ["editorial", "utilitarian", "playful", "technical"], "default": "utilitarian"}, "theme_aware": {"type": "boolean", "default": True}, "seed_color": {"type": "string"}}, "required": ["query"]},
        "handler": tool_generate_design_system,
    },
    "create_component": {
        "description": "Generate a component specification (sizing, spacing, states, variants) with ready-to-use HTML/CSS or React/Tailwind markup.",
        "inputSchema": {"type": "object", "properties": {"component": {"type": "string", "description": "e.g. 'primary button', 'data table', 'pricing card'"}, "tokens": {"type": "object", "description": "Design tokens to apply"}, "framework": {"type": "string", "enum": ["html-css", "react-tailwind"], "default": "html-css"}}, "required": ["component"]},
        "handler": tool_create_component,
    },
    "compose_page": {
        "description": "Compose a full HTML page from a layout pattern (hero, dashboard, sidebar, pricing, feature_grid, footer) and design tokens.",
        "inputSchema": {"type": "object", "properties": {"pattern": {"type": "string", "description": "e.g. 'dashboard', 'hero', 'pricing_table', 'sidebar_layout'"}, "tokens": {"type": "object"}, "content": {"type": "object", "description": "Copy/data to fill: title, subtitle, cta, main_content, etc."}}, "required": ["pattern", "tokens"]},
        "handler": tool_compose_page,
    },
    "export": {
        "description": "Export generated design output as a file or push to a Compose-compatible host for a shareable preview URL.",
        "inputSchema": {"type": "object", "properties": {"content": {"type": "string"}, "content_type": {"type": "string", "enum": ["html", "css", "svg", "markdown", "json"]}, "target": {"type": "string", "enum": ["file", "compose_host"], "default": "file"}, "title": {"type": "string"}}, "required": ["content", "content_type"]},
        "handler": tool_export,
    },
    "render_visual": {
        "description": "Render a visual image via aivision — badges, charts, palette swatches, gradients, patterns, composites. Returns base64 PNG.",
        "inputSchema": {"type": "object", "properties": {"type": {"type": "string", "enum": ["solid", "gradient", "pattern", "badge", "chart_bar", "palette_swatch", "composite"], "description": "Image type to render"}, "width": {"type": "integer"}, "height": {"type": "integer"}, "text": {"type": "string"}, "color": {}, "start": {}, "end": {}, "values": {"type": "array"}, "labels": {"type": "array"}, "colors": {"type": "array"}, "save_path": {"type": "string"}}, "required": ["type"]},
        "handler": tool_render_visual,
    },
    "design_critique": {
        "description": "Critique a set of design tokens for accessibility, contrast, spacing consistency, and common design mistakes.",
        "inputSchema": {"type": "object", "properties": {"tokens": {"type": "object", "description": "Design tokens to critique (color roles, spacing array, etc.)"}}, "required": ["tokens"]},
        "handler": tool_design_critique,
    },
}


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def _handle_request(req: dict) -> dict | None:
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "composer-mcp", "version": "0.2.0"}, "capabilities": {"tools": {}}}}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": [{"name": name, "description": spec["description"], "inputSchema": spec["inputSchema"]} for name, spec in TOOLS.items()]}}

    if method == "tools/call":
        params = req.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"unknown tool: {name}"}}
        try:
            result = TOOLS[name]["handler"](args)
            return {"jsonrpc": "2.0", "id": req_id, "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(exc)}}

    if method == "notifications/initialized":
        return None

    if req_id is None:
        return None

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

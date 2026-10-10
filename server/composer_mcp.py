#!/usr/bin/env python3
"""Composer MCP v2 — design system MCP with Paul Rand brand discipline.

9 tools: palette, brand_guidelines, generate_design_system, create_component,
  compose_page, export, render_visual, design_critique, export_tokens

Speaks MCP over stdio (JSON-RPC 2.0, newline-delimited).
Optional aivision bridge for image rendering (AIVISION_URL env var).
"""

import base64
import colorsys
import json
import math
import os
import re
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

_HEX_RE = re.compile(r"^#?[0-9a-fA-F]{6}$")


def _valid_hex(c: str) -> bool:
    return bool(c and _HEX_RE.match(c))


def _sanitize_hex(c: str) -> str:
    c = c.strip()
    if not c.startswith("#"):
        c = "#" + c
    if not _valid_hex(c):
        raise ValueError(f"invalid hex color: {c}")
    return c.lower()


def _hsl_to_hex(h: float, s: float, l: float) -> str:
    r, g, b = colorsys.hls_to_rgb(h / 360.0, l, s)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _simulate_cvd(hex_color: str, deficiency: str) -> str:
    r, g, b = [c / 255.0 for c in _hex_to_rgb(hex_color)]
    matrices = {
        "protanopia": ((0.567, 0.433, 0.0), (0.558, 0.442, 0.0), (0.0, 0.242, 0.758)),
        "deuteranopia": ((0.625, 0.375, 0.0), (0.7, 0.3, 0.0), (0.0, 0.3, 0.7)),
        "tritanopia": ((0.95, 0.05, 0.0), (0.0, 0.433, 0.567), (0.0, 0.475, 0.525)),
    }
    m = matrices.get(deficiency, matrices["deuteranopia"])
    sr = min(1, max(0, m[0][0] * r + m[0][1] * g + m[0][2] * b))
    sg = min(1, max(0, m[1][0] * r + m[1][1] * g + m[1][2] * b))
    sb = min(1, max(0, m[2][0] * r + m[2][1] * g + m[2][2] * b))
    return "#{:02x}{:02x}{:02x}".format(round(sr * 255), round(sg * 255), round(sb * 255))


def _color_distance(c1: str, c2: str) -> float:
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return math.sqrt((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2)


def _relative_luminance(hex_color: str) -> float:
    hex_color = hex_color.lstrip("#")
    rgb = [int(hex_color[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast_ratio(fg: str, bg: str) -> float:
    l1, l2 = _relative_luminance(fg), _relative_luminance(bg)
    lighter, darker = max(l1, l2), min(l1, l2)
    return round((lighter + 0.05) / (darker + 0.05), 2)


# ── Constants ──

_BREAKPOINTS = {"sm": 640, "md": 768, "lg": 1024, "xl": 1280, "2xl": 1536}
_Z_INDEX = {"dropdown": 1000, "sticky": 1020, "fixed": 1030, "modal-backdrop": 1040, "modal": 1050, "popover": 1060, "tooltip": 1070, "toast": 1080}
_TRANSITIONS = {"fast": "150ms ease", "normal": "200ms ease", "slow": "300ms ease-out", "spring": "500ms cubic-bezier(0.34,1.56,0.64,1)"}

_MOTION_TOKENS = {
    "easing": {
        "mark": "cubic-bezier(0.22, 1, 0.36, 1)",
        "page": "ease-out",
        "spring": "cubic-bezier(0.34, 1.56, 0.64, 1)",
        "smooth": "ease-in-out",
    },
    "duration": {
        "micro": 120,
        "settle": 240,
        "land": 320,
        "draw": 400,
        "reveal": 520,
        "count": 960,
    },
}

_ANIMATION_PRESETS = {
    "reveal-in": "@keyframes reveal-in { from { opacity:0; transform:translateY(18px) } to { opacity:1; transform:translateY(0) } }",
    "fold-open": "@keyframes fold-open { from { max-height:0; opacity:0 } to { max-height:500px; opacity:1 } }",
    "bar-grow": "@keyframes bar-grow { from { width:0 } to { width:var(--bar-size) } }",
    "core-land": "@keyframes core-land { 0% { transform:scale(0) } 70% { transform:scale(1.18) } 100% { transform:scale(1) } }",
    "live-pulse": "@keyframes live-pulse { 0%,100% { transform:scale(1); opacity:0.92 } 50% { transform:scale(1.12); opacity:1 } }",
    "row-settle": "@keyframes row-settle { from { opacity:0; transform:translateY(14px) } to { opacity:1; transform:translateY(0) } }",
    "sweep-in": "@keyframes sweep-in { from { transform:translateX(-100%); opacity:0 } to { transform:translateX(0); opacity:1 } }",
    "ring-draw": "@keyframes ring-draw { to { stroke-dashoffset:0 } }",
}

_SHADOW_PAIRS = {
    "sm": {
        "rest": "0 1px 2px rgba(0,0,0,0.04), 0 4px 8px -4px rgba(0,0,0,0.06)",
        "hover": "0 2px 4px rgba(0,0,0,0.05), 0 12px 24px -8px rgba(0,0,0,0.12)",
    },
    "md": {
        "rest": "0 1px 2px rgba(0,0,0,0.04), 0 6px 16px -8px rgba(0,0,0,0.10)",
        "hover": "0 2px 4px rgba(0,0,0,0.05), 0 18px 40px -16px rgba(0,0,0,0.20)",
    },
    "lg": {
        "rest": "0 4px 8px rgba(0,0,0,0.06), 0 16px 32px -12px rgba(0,0,0,0.14)",
        "hover": "0 8px 16px rgba(0,0,0,0.08), 0 32px 64px -16px rgba(0,0,0,0.24)",
    },
}

_COLOR_USAGE_RULES = {
    "accent": {"allowed": ["cta", "link", "focus-ring", "badge"], "forbidden": ["field-fill", "background", "large-surface"]},
    "error": {"allowed": ["badge", "border-left", "icon", "text"], "forbidden": ["field-fill", "primary-button", "background"]},
    "signal": {"allowed": ["mark", "rule", "cross", "indicator"], "forbidden": ["field", "background", "large-surface"]},
    "warning": {"allowed": ["badge", "border", "icon"], "forbidden": ["primary-button", "heading"]},
    "success": {"allowed": ["badge", "border", "icon", "indicator"], "forbidden": ["primary-button", "heading"]},
}

_BRAND_PRESETS = {
    "restrained": {
        "description": "Restrained, evidence-based. Mono for data, serif for display. Signal colors for marks only. One animated element maximum.",
        "type_pair": ("Space Grotesk", "JetBrains Mono", 1.5),
        "color_philosophy": "Signal red for marks/rules/crosses only, never fields. Accent for CTAs only.",
        "motion_philosophy": "minimal",
        "radius": {"sm": 4, "md": 8, "lg": 8, "xl": 8, "full": 9999},
        "type_constraints": {"display_max_lines": 1, "display_min_size": 28, "display_caps": False, "display_letterspacing": False, "body_min_size": 14, "label_face": "mono"},
    },
    "editorial": {
        "description": "Warm, narrative, generous whitespace. Serif headlines, sans body.",
        "type_pair": ("Playfair Display", "Source Sans 3", 1.6),
        "color_philosophy": "Muted palette with one accent for emphasis. Warm neutrals.",
        "motion_philosophy": "measured",
        "radius": {"sm": 4, "md": 8, "lg": 12, "xl": 16, "full": 9999},
        "type_constraints": {"display_max_lines": 2, "display_min_size": 24, "display_caps": False, "display_letterspacing": False, "body_min_size": 16, "label_face": "sans"},
    },
    "utilitarian": {
        "description": "Clean, dense, functional. Sans heading and body.",
        "type_pair": ("Inter", "Inter", 1.5),
        "color_philosophy": "Functional color roles. Blue for actions, red for errors, green for success.",
        "motion_philosophy": "standard",
        "radius": {"sm": 4, "md": 8, "lg": 12, "xl": 16, "full": 9999},
        "type_constraints": {"display_max_lines": 3, "display_min_size": 20, "display_caps": True, "display_letterspacing": True, "body_min_size": 14, "label_face": "sans"},
    },
    "playful": {
        "description": "Rounded, bouncy, approachable. Spring easing, large radii.",
        "type_pair": ("Nunito", "Nunito", 1.6),
        "color_philosophy": "Vibrant, saturated palette. Multiple accent colors allowed.",
        "motion_philosophy": "expressive",
        "radius": {"sm": 8, "md": 12, "lg": 16, "xl": 24, "full": 9999},
        "type_constraints": {"display_max_lines": 3, "display_min_size": 20, "display_caps": True, "display_letterspacing": True, "body_min_size": 14, "label_face": "sans"},
    },
    "technical": {
        "description": "Precise, monospaced, minimal. Data-first.",
        "type_pair": ("JetBrains Mono", "JetBrains Mono", 1.45),
        "color_philosophy": "Neutral ground, monochrome data. Color only for state changes.",
        "motion_philosophy": "minimal",
        "radius": {"sm": 2, "md": 4, "lg": 6, "xl": 8, "full": 9999},
        "type_constraints": {"display_max_lines": 2, "display_min_size": 18, "display_caps": True, "display_letterspacing": True, "body_min_size": 13, "label_face": "mono"},
    },
}

_CONTEXT_HUES = {
    "fintech": 215, "healthcare": 165, "dashboard": 230,
    "ecommerce": 20, "editorial": 15, "developer": 260,
    "saas": 225, "social": 200, "gaming": 280, "education": 145,
}

_TYPE_SCALE = {"xs": 12, "sm": 14, "base": 16, "lg": 18, "xl": 20, "2xl": 24, "3xl": 30, "4xl": 36, "5xl": 48}
_SPACING_SCALE = [0, 4, 8, 12, 16, 20, 24, 32, 40, 48, 64, 80, 96]

_TYPE_PAIRS = {
    "editorial": ("Playfair Display", "Source Sans 3", 1.6),
    "utilitarian": ("Inter", "Inter", 1.5),
    "playful": ("Nunito", "Nunito", 1.6),
    "technical": ("JetBrains Mono", "JetBrains Mono", 1.45),
    "restrained": ("Space Grotesk", "JetBrains Mono", 1.5),
}

_COMPONENT_SPECS = {
    "button": {"variants": ["primary", "secondary", "outline", "ghost", "destructive"], "sizes": {"sm": {"px": 12, "py": 6, "font": 14}, "md": {"px": 16, "py": 10, "font": 16}, "lg": {"px": 24, "py": 14, "font": 18}}, "states": ["default", "hover", "active", "focus", "disabled"], "radius": 8},
    "card": {"variants": ["elevated", "outlined", "filled"], "sizes": {"sm": {"padding": 16}, "md": {"padding": 24}, "lg": {"padding": 32}}, "states": ["default", "hover"], "radius": 12},
    "input": {"variants": ["outlined", "filled", "underlined"], "sizes": {"sm": {"px": 12, "py": 8, "font": 14}, "md": {"px": 16, "py": 12, "font": 16}, "lg": {"px": 20, "py": 16, "font": 18}}, "states": ["default", "focus", "error", "disabled"], "radius": 8},
    "badge": {"variants": ["solid", "outline", "soft"], "sizes": {"sm": {"px": 6, "py": 2, "font": 11}, "md": {"px": 8, "py": 4, "font": 12}}, "states": ["default"], "radius": 9999},
    "modal": {"variants": ["default", "fullscreen", "drawer"], "sizes": {"sm": {"max_width": 400}, "md": {"max_width": 560}, "lg": {"max_width": 720}}, "states": ["open", "closed"], "radius": 16},
    "avatar": {"variants": ["circle", "rounded"], "sizes": {"xs": {"dim": 24}, "sm": {"dim": 32}, "md": {"dim": 40}, "lg": {"dim": 56}, "xl": {"dim": 80}}, "states": ["default"], "radius": 9999},
    "toast": {"variants": ["info", "success", "warning", "error"], "sizes": {"default": {"max_width": 360}}, "states": ["visible", "dismissed"], "radius": 8},
    "tabs": {"variants": ["underline", "pill", "enclosed"], "sizes": {"sm": {"py": 8, "font": 14}, "md": {"py": 12, "font": 16}}, "states": ["default", "active", "disabled"], "radius": 8},
    "nav": {"variants": ["horizontal", "vertical", "sidebar"], "sizes": {"default": {"height": 64}}, "states": ["default", "active", "hover"], "radius": 8},
    "table": {"variants": ["striped", "bordered", "minimal"], "sizes": {"compact": {"py": 8, "font": 14}, "default": {"py": 12, "font": 16}, "spacious": {"py": 16, "font": 16}}, "states": ["default", "hover", "selected"], "radius": 8},
}

_LAYOUT_PATTERNS = {
    "hero": '<section style="padding:80px 40px;text-align:center;background:{bg};color:{text}"><h1 style="font-family:{heading};font-size:48px;margin-bottom:16px">{title}</h1><p style="font-size:20px;max-width:640px;margin:0 auto 32px;opacity:0.8">{subtitle}</p><a href="#" style="display:inline-block;padding:14px 32px;background:{primary};color:#fff;border-radius:8px;text-decoration:none;font-weight:600">{cta}</a></section>',
    "feature_grid": '<section style="padding:64px 40px;background:{surface}"><div style="display:grid;grid-template-columns:repeat(3,1fr);gap:24px;max-width:1200px;margin:0 auto">{features}</div></section>',
    "sidebar_layout": '<div style="display:flex;min-height:100vh"><aside style="width:260px;background:{surface};border-right:1px solid {border};padding:24px"><nav>{nav_items}</nav></aside><main style="flex:1;padding:32px;background:{bg};color:{text}">{main_content}</main></div>',
    "pricing_table": '<section style="padding:64px 40px;background:{bg};color:{text};text-align:center"><h2 style="font-family:{heading};font-size:36px;margin-bottom:48px">{title}</h2><div style="display:flex;gap:24px;justify-content:center;flex-wrap:wrap">{plans}</div></section>',
    "dashboard": '<div style="display:grid;grid-template-columns:260px 1fr;grid-template-rows:64px 1fr;min-height:100vh"><header style="grid-column:1/-1;background:{surface};border-bottom:1px solid {border};display:flex;align-items:center;padding:0 24px;color:{text};font-family:{heading}">{header}</header><aside style="background:{surface};border-right:1px solid {border};padding:16px">{sidebar}</aside><main style="padding:24px;background:{bg};color:{text}">{main_content}</main></div>',
    "footer": '<footer style="padding:48px 40px;background:{surface};color:{text};border-top:1px solid {border}"><div style="display:flex;justify-content:space-between;max-width:1200px;margin:0 auto">{columns}</div></footer>',
    "receipt_card": '<div style="display:grid;grid-template-columns:1.3fr 0.8fr;gap:20px;max-width:1000px"><div style="padding:24px;background:{surface};border:1px solid {border};border-radius:8px"><span style="font-family:monospace;font-size:11px;letter-spacing:0.18em;text-transform:uppercase;color:{text};opacity:0.5">{question_label}</span><div style="display:flex;align-items:end;gap:14px;margin:18px 0 16px"><span style="font-family:serif;font-size:clamp(3rem,6vw,4.8rem);line-height:0.9;color:{text}">{stat}</span><span style="font-family:monospace;font-size:11px;letter-spacing:0.16em;text-transform:uppercase;color:{text};opacity:0.5;padding-bottom:10px">{stat_label}</span></div><h3 style="font-family:{heading};color:{text};margin-bottom:12px">{title}</h3><p style="color:{text};opacity:0.62;max-width:720px">{subtitle}</p></div><div style="padding:24px;background:{surface};border:1px solid {border};border-radius:8px"><h3 style="font-family:{heading};color:{text};margin-bottom:12px">{receipt_title}</h3><ul style="list-style:none;display:grid;gap:12px;padding:0">{receipt_items}</ul></div></div>',
    "chat_thread": '<div style="max-width:480px;display:flex;flex-direction:column;gap:14px;padding:18px 16px"><div style="align-self:flex-end;max-width:84%;padding:12px 14px;border-radius:16px 16px 6px 16px;background:{surface};border:1px solid {border};color:{text};opacity:0.62;font-size:14px">{question}</div><div style="padding:18px 16px;border-left:2px solid {primary};border-radius:6px 16px 16px 6px;background:{surface};border:1px solid {border};box-shadow:{shadow}"><h3 style="font-family:{heading};color:{text};margin-bottom:8px;font-size:18px">{title}</h3><p style="color:{text};opacity:0.62;font-size:14px;max-width:none">{subtitle}</p></div></div>',
    "matrix_grid": '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:20px;max-width:1200px">{cells}</div>',
    "card_stack": '<div style="position:relative;width:320px;height:240px">{stack_cards}</div>',
}


# ── Palette builder ──

def _build_palette(context: str, mode: str, seed_color: str | None) -> dict:
    ctx_lower = context.lower()
    hue = 220
    for keyword, h in _CONTEXT_HUES.items():
        if keyword in ctx_lower:
            hue = h
            break
    else:
        hue = sum(ord(c) for c in context) % 360

    if seed_color and _valid_hex(seed_color):
        r, g, b = _hex_to_rgb(seed_color.lstrip("#"))
        h_norm, _, _ = colorsys.rgb_to_hls(r / 255.0, g / 255.0, b / 255.0)
        hue = round(h_norm * 360)

    if mode == "dark":
        roles = {
            "primary": _hsl_to_hex(hue, 0.7, 0.55),
            "secondary": _hsl_to_hex((hue + 30) % 360, 0.5, 0.45),
            "accent": _hsl_to_hex((hue + 180) % 360, 0.65, 0.55),
            "background": _hsl_to_hex(hue, 0.15, 0.08),
            "surface": _hsl_to_hex(hue, 0.12, 0.12),
            "text": "#f5f5f5",
            "border": _hsl_to_hex(hue, 0.1, 0.2),
            "error": "#ef4444",
            "success": "#16a34a",
            "warning": "#d97706",
        }
    else:
        roles = {
            "primary": _hsl_to_hex(hue, 0.65, 0.45),
            "secondary": _hsl_to_hex((hue + 30) % 360, 0.45, 0.55),
            "accent": _hsl_to_hex((hue + 180) % 360, 0.6, 0.5),
            "background": "#ffffff",
            "surface": "#f9fafb",
            "text": "#111827",
            "border": "#e5e7eb",
            "error": "#dc2626",
            "success": "#16a34a",
            "warning": "#d97706",
        }

    if seed_color and _valid_hex(seed_color):
        roles["primary"] = _sanitize_hex(seed_color)

    contrast = _contrast_ratio(roles["primary"], roles["background"])
    return {"mode": mode, "roles": roles, "primary_contrast": {"ratio": contrast, "passes_aa_large": contrast >= 3.0, "passes_aa": contrast >= 4.5}}


# ── Aivision bridge ──

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


# ── Token export formats ──

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
    for name, val in _MOTION_TOKENS["easing"].items():
        lines.append(f"  --ease-{name}: {val};")
    for name, ms in _MOTION_TOKENS["duration"].items():
        lines.append(f"  --{name}: {ms}ms;")
    for size, pair in _SHADOW_PAIRS.items():
        lines.append(f"  --shadow-{size}: {pair['rest']};")
        lines.append(f"  --shadow-{size}-hover: {pair['hover']};")
    lines.append("}")
    lines.append("")
    for name, keyframe in _ANIMATION_PRESETS.items():
        lines.append(keyframe)
    lines.append("")
    lines.append("@media (prefers-reduced-motion: reduce) {")
    lines.append("  *, *::before, *::after {")
    lines.append("    animation-duration: 0.01ms !important;")
    lines.append("    animation-iteration-count: 1 !important;")
    lines.append("    transition-duration: 0.01ms !important;")
    lines.append("  }")
    lines.append("}")
    return "\n".join(lines)


def _tokens_to_tailwind(tokens: dict) -> str:
    colors = {}
    for role, val in tokens.get("color", {}).items():
        colors[role] = val
    spacing = {}
    for i, s in enumerate(tokens.get("spacing", _SPACING_SCALE)):
        spacing[str(i)] = f"{s}px"
    font_size = {}
    for name, px in tokens.get("type_scale", _TYPE_SCALE).items():
        font_size[name] = f"{px}px"
    shadow = {}
    for size, pair in _SHADOW_PAIRS.items():
        shadow[size] = pair["rest"]
        shadow[f"{size}-hover"] = pair["hover"]
    transition_timing = {}
    for name, val in _MOTION_TOKENS["easing"].items():
        transition_timing[name] = val
    transition_duration = {}
    for name, ms in _MOTION_TOKENS["duration"].items():
        transition_duration[name] = f"{ms}ms"
    config = {
        "theme": {
            "extend": {
                "colors": colors,
                "spacing": spacing,
                "fontSize": font_size,
                "boxShadow": shadow,
                "transitionTimingFunction": transition_timing,
                "transitionDuration": transition_duration,
                "fontFamily": {},
            }
        }
    }
    if tokens.get("heading_font"):
        config["theme"]["extend"]["fontFamily"]["heading"] = [tokens["heading_font"], "sans-serif"]
    if tokens.get("body_font"):
        config["theme"]["extend"]["fontFamily"]["body"] = [tokens["body_font"], "sans-serif"]
    return f"module.exports = {json.dumps(config, indent=2)}"


def _tokens_to_figma(tokens: dict) -> str:
    figma = {}
    for role, val in tokens.get("color", {}).items():
        figma[f"color/{role}"] = {"value": val, "type": "color"}
    for name, px in tokens.get("type_scale", _TYPE_SCALE).items():
        figma[f"fontSize/{name}"] = {"value": px, "type": "fontSizes"}
    for i, s in enumerate(tokens.get("spacing", _SPACING_SCALE)):
        figma[f"spacing/{i}"] = {"value": s, "type": "spacing"}
    for size, pair in _SHADOW_PAIRS.items():
        figma[f"shadow/{size}"] = {"value": pair["rest"], "type": "boxShadow"}
        figma[f"shadow/{size}-hover"] = {"value": pair["hover"], "type": "boxShadow"}
    for name, ms in _MOTION_TOKENS["duration"].items():
        figma[f"motion/{name}"] = {"value": f"{ms}ms", "type": "duration"}
    return json.dumps(figma, indent=2)


def _tokens_to_style_dictionary(tokens: dict) -> str:
    sd = {"color": {}, "size": {"font": {}, "spacing": {}}, "shadow": {}, "motion": {"duration": {}, "easing": {}}}
    for role, val in tokens.get("color", {}).items():
        sd["color"][role] = {"value": val}
    for name, px in tokens.get("type_scale", _TYPE_SCALE).items():
        sd["size"]["font"][name] = {"value": px}
    for i, s in enumerate(tokens.get("spacing", _SPACING_SCALE)):
        sd["size"]["spacing"][str(i)] = {"value": s}
    for size, pair in _SHADOW_PAIRS.items():
        sd["shadow"][size] = {"value": pair["rest"]}
        sd["shadow"][f"{size}_hover"] = {"value": pair["hover"]}
    for name, ms in _MOTION_TOKENS["duration"].items():
        sd["motion"]["duration"][name] = {"value": f"{ms}ms"}
    for name, val in _MOTION_TOKENS["easing"].items():
        sd["motion"]["easing"][name] = {"value": val}
    return json.dumps(sd, indent=2)


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
    preset_name = args.get("preset", tone if tone in _BRAND_PRESETS else "utilitarian")
    preset = _BRAND_PRESETS.get(preset_name, _BRAND_PRESETS["utilitarian"])
    palette = _build_palette(product_description, "both", None)
    heading_font, body_font, line_height = preset["type_pair"]
    tc = preset["type_constraints"]

    markdown = f"""# Brand Guidelines — {product_description.strip().title()}

## Personality
**{preset_name.title()}** — {preset['description']}

## Tone
{tone.title()} — {preset['color_philosophy']}

## Palette
| Role | Hex |
|---|---|
""" + "\n".join(f"| {role} | `{hex_val}` |" for role, hex_val in palette["roles"].items()) + f"""

## Color Usage Rules
""" + "\n".join(f"- **{role}**: allowed in {', '.join(rules['allowed'])}; never in {', '.join(rules['forbidden'])}" for role, rules in _COLOR_USAGE_RULES.items()) + f"""

## Typography
- Heading: **{heading_font}** / line-height {line_height}
- Body: **{body_font}** / line-height {line_height + 0.1}
- Scale: {', '.join(f'{k}={v}px' for k, v in _TYPE_SCALE.items())}
- Display: max {tc['display_max_lines']} line(s), min {tc['display_min_size']}px{', never caps' if not tc['display_caps'] else ''}{', never letterspaced' if not tc['display_letterspacing'] else ''}
- Labels: {tc['label_face']} face

## Spacing
Scale (px): {', '.join(str(s) for s in _SPACING_SCALE)}

## Motion
Philosophy: **{preset['motion_philosophy']}**
| Token | Duration |
|---|---|
""" + "\n".join(f"| {name} | {ms}ms |" for name, ms in _MOTION_TOKENS["duration"].items()) + """

| Easing | Curve |
|---|---|
""" + "\n".join(f"| {name} | `{curve}` |" for name, curve in _MOTION_TOKENS["easing"].items()) + f"""

## Shadows
| Size | Resting | Hover |
|---|---|---|
""" + "\n".join(f"| {size} | `{pair['rest'][:40]}...` | `{pair['hover'][:40]}...` |" for size, pair in _SHADOW_PAIRS.items()) + """

## Do
- Keep contrast at or above WCAG AA (4.5:1) for all body text.
- Use the accent color sparingly — calls to action only.
- Maintain consistent spacing from the scale — never ad-hoc pixel values.
- Honor prefers-reduced-motion in all animations.

## Don't
- Don't introduce a second accent color without a documented reason.
- Don't set body text below 14px.
- Don't mix type families outside the heading/body pair.
- Don't use animations longer than 960ms without justification.
"""
    tokens = {"color": palette["roles"], "type": {"heading_font": heading_font, "body_font": body_font}, "spacing": {"scale": _SPACING_SCALE}}
    return {"markdown": markdown, "tokens": tokens, "preset": preset_name}


# ── Tool: generate_design_system ──

def tool_generate_design_system(args: dict) -> dict:
    query = args["query"]
    treatment = args.get("treatment", "utilitarian")
    theme_aware = args.get("theme_aware", True)
    preset_name = args.get("preset", treatment if treatment in _BRAND_PRESETS else "utilitarian")
    preset = _BRAND_PRESETS.get(preset_name, _BRAND_PRESETS["utilitarian"])

    heading_font, body_font, line_height = preset["type_pair"]

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
    tokens_css = _tokens_to_css({"color": first_palette["roles"], "type_scale": _TYPE_SCALE, "spacing": _SPACING_SCALE, "heading_font": heading_font, "body_font": body_font})
    tokens_tailwind = _tokens_to_tailwind({"color": first_palette["roles"], "type_scale": _TYPE_SCALE, "spacing": _SPACING_SCALE, "heading_font": heading_font, "body_font": body_font})
    tokens_figma = _tokens_to_figma({"color": first_palette["roles"], "type_scale": _TYPE_SCALE, "spacing": _SPACING_SCALE})
    tokens_style_dict = _tokens_to_style_dictionary({"color": first_palette["roles"], "type_scale": _TYPE_SCALE, "spacing": _SPACING_SCALE})

    cvd_report = {}
    for deficiency in ("protanopia", "deuteranopia", "tritanopia"):
        sim_primary = _simulate_cvd(first_palette["roles"]["primary"], deficiency)
        sim_bg = _simulate_cvd(first_palette["roles"]["background"], deficiency)
        ratio = _contrast_ratio(sim_primary, sim_bg)
        cvd_report[deficiency] = {"simulated_primary": sim_primary, "contrast_vs_bg": ratio, "passes_3_1": ratio >= 3.0}

    return {
        "design_system": {
            "preset": preset_name,
            "preset_description": preset["description"],
            "palette": palettes,
            "typography": typography,
            "type_constraints": preset["type_constraints"],
            "spacing": {"scale": _SPACING_SCALE, "unit": "px"},
            "breakpoints": _BREAKPOINTS,
            "z_index": _Z_INDEX,
            "transitions": _TRANSITIONS,
            "motion": _MOTION_TOKENS,
            "animations": list(_ANIMATION_PRESETS.keys()),
            "shadows": _SHADOW_PAIRS,
            "color_usage_rules": _COLOR_USAGE_RULES,
            "grid": {"columns": 12, "gutter": 24, "margin": 16, "max_width": 1280},
            "border_radius": preset["radius"],
            "components": components,
            "accessibility": accessibility,
            "color_vision_deficiency": cvd_report,
        },
        "tokens_css": tokens_css,
        "tokens_tailwind": tokens_tailwind,
        "tokens_figma": tokens_figma,
        "tokens_style_dictionary": tokens_style_dict,
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
        return f'<button style="padding:10px 16px;background:{primary};color:#fff;border:none;border-radius:{radius}px;font-size:16px;cursor:pointer;font-weight:600;transition:opacity 150ms ease" onmouseover="this.style.opacity=0.9" onmouseout="this.style.opacity=1">Button</button>'
    if name == "card":
        return f'<div style="background:{surface};border:1px solid {border};border-radius:{radius}px;padding:24px;color:{text};box-shadow:{_SHADOW_PAIRS["sm"]["rest"]};transition:box-shadow 240ms ease"><h3 style="margin:0 0 8px">Card Title</h3><p style="margin:0;opacity:0.7">Card description text goes here.</p></div>'
    if name == "input":
        return f'<div><label style="display:block;margin-bottom:4px;font-size:14px;font-weight:500;color:{text}">Label</label><input type="text" placeholder="Placeholder" style="width:100%;padding:12px 16px;border:1px solid {border};border-radius:{radius}px;font-size:16px;background:{bg};color:{text};outline:none;box-sizing:border-box;transition:border-color 120ms ease" onfocus="this.style.borderColor=\'{primary}\'" onblur="this.style.borderColor=\'{border}\'"></div>'
    if name == "badge":
        return f'<span style="display:inline-block;padding:4px 8px;background:{primary};color:#fff;border-radius:{radius}px;font-size:12px;font-weight:600">Badge</span>'
    if name == "toast":
        return f'<div style="padding:16px;background:{surface};border:1px solid {border};border-left:4px solid {primary};border-radius:{radius}px;color:{text};display:flex;align-items:center;gap:12px;max-width:360px;box-shadow:{_SHADOW_PAIRS["md"]["rest"]}"><span style="font-weight:500">Notification message</span></div>'
    if name == "avatar":
        return f'<div style="width:40px;height:40px;border-radius:{radius}px;background:{primary};color:#fff;display:flex;align-items:center;justify-content:center;font-weight:600;font-size:16px">JD</div>'
    return f'<div style="padding:16px;border:1px solid {border};border-radius:{radius}px;color:{text};background:{surface}"><!-- {name} component --></div>'


def _component_react(name: str, spec: dict, tokens: dict) -> str:
    p = tokens or {}
    primary = p.get("primary", "#3b82f6")
    border = p.get("border", "#e5e7eb")
    surface = p.get("surface", "#f9fafb")
    text_c = p.get("text", "#111827")
    _react = {
        "button": f'''export function Button({{ children, variant = "primary", size = "md", disabled, ...props }}) {{
  const base = "inline-flex items-center justify-center font-semibold transition-all focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[{primary}] disabled:opacity-50 disabled:cursor-not-allowed";
  const variants = {{ primary: "bg-[{primary}] text-white hover:opacity-90", secondary: "bg-[{surface}] text-[{text_c}] border border-[{border}] hover:bg-[{border}]", outline: "bg-transparent text-[{primary}] border border-[{primary}] hover:bg-[{primary}]/10", ghost: "bg-transparent text-[{text_c}] hover:bg-[{surface}]", destructive: "bg-red-600 text-white hover:bg-red-700" }};
  const sizes = {{ sm: "px-3 py-1.5 text-sm rounded-md gap-1.5", md: "px-4 py-2.5 text-base rounded-lg gap-2", lg: "px-6 py-3.5 text-lg rounded-lg gap-2.5" }};
  return <button className={{`${{base}} ${{variants[variant]}} ${{sizes[size]}}`}} disabled={{disabled}} {{...props}}>{{children}}</button>;
}}''',
        "card": f'''export function Card({{ children, variant = "elevated", className, ...props }}) {{
  const variants = {{ elevated: "shadow-md hover:shadow-lg bg-[{surface}]", outlined: "border border-[{border}] bg-[{surface}]", filled: "bg-[{surface}]" }};
  return <div className={{`rounded-xl p-6 text-[{text_c}] transition-shadow duration-[240ms] ease-[cubic-bezier(0.22,1,0.36,1)] ${{variants[variant]}} ${{className || ""}}`}} {{...props}}>{{children}}</div>;
}}''',
        "input": f'''export function Input({{ label, error, size = "md", variant = "outlined", ...props }}) {{
  const sizes = {{ sm: "px-3 py-2 text-sm", md: "px-4 py-3 text-base", lg: "px-5 py-4 text-lg" }};
  const variants = {{ outlined: "border border-[{border}] bg-transparent", filled: "border-0 bg-[{surface}]", underlined: "border-0 border-b-2 border-[{border}] rounded-none bg-transparent" }};
  return (
    <div className="flex flex-col gap-1">
      {{label && <label className="text-sm font-medium text-[{text_c}]">{{label}}</label>}}
      <input className={{`rounded-lg text-[{text_c}] outline-none transition-colors duration-[120ms] focus:border-[{primary}] focus:ring-2 focus:ring-[{primary}]/20 disabled:opacity-50 ${{sizes[size]}} ${{variants[variant]}} ${{error ? "border-red-500" : ""}}`}} {{...props}} />
      {{error && <span className="text-sm text-red-500">{{error}}</span>}}
    </div>
  );
}}''',
        "badge": f'''export function Badge({{ children, variant = "solid", color = "{primary}" }}) {{
  const variants = {{ solid: `bg-[${{color}}] text-white`, outline: `border border-[${{color}}] text-[${{color}}]`, soft: `bg-[${{color}}]/10 text-[${{color}}]` }};
  return <span className={{`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${{variants[variant]}}`}}>{{children}}</span>;
}}''',
        "modal": f'''export function Modal({{ open, onClose, title, children, size = "md" }}) {{
  const sizes = {{ sm: "max-w-sm", md: "max-w-lg", lg: "max-w-2xl", full: "max-w-full mx-4" }};
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[1050] flex items-center justify-center" role="dialog" aria-modal="true">
      <div className="fixed inset-0 bg-black/50 backdrop-blur-sm" onClick={{onClose}} />
      <div className={{`relative bg-[{surface}] text-[{text_c}] rounded-2xl shadow-xl p-6 w-full ${{sizes[size]}} animate-in fade-in zoom-in-95`}}>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">{{title}}</h2>
          <button onClick={{onClose}} className="p-1 rounded-md hover:bg-[{border}]" aria-label="Close">&times;</button>
        </div>
        {{children}}
      </div>
    </div>
  );
}}''',
        "avatar": f'''export function Avatar({{ src, alt, fallback, size = "md" }}) {{
  const sizes = {{ xs: "w-6 h-6 text-xs", sm: "w-8 h-8 text-sm", md: "w-10 h-10 text-base", lg: "w-14 h-14 text-xl", xl: "w-20 h-20 text-2xl" }};
  return (
    <div className={{`rounded-full bg-[{primary}] text-white flex items-center justify-center font-semibold overflow-hidden ${{sizes[size]}}`}}>
      {{src ? <img src={{src}} alt={{alt}} className="w-full h-full object-cover" /> : (fallback || "?")}}
    </div>
  );
}}''',
        "toast": f'''export function Toast({{ message, variant = "info", onDismiss }}) {{
  const icons = {{ info: "ℹ", success: "✓", warning: "⚠", error: "✕" }};
  const colors = {{ info: "{primary}", success: "#22c55e", warning: "#f59e0b", error: "#ef4444" }};
  return (
    <div className="flex items-center gap-3 bg-[{surface}] border border-[{border}] rounded-lg p-4 shadow-lg max-w-[360px]" style={{{{ borderLeftColor: colors[variant], borderLeftWidth: 4 }}}} role="alert">
      <span style={{{{ color: colors[variant] }}}}>{{icons[variant]}}</span>
      <span className="flex-1 text-sm text-[{text_c}]">{{message}}</span>
      {{onDismiss && <button onClick={{onDismiss}} className="text-[{text_c}]/50 hover:text-[{text_c}]" aria-label="Dismiss">&times;</button>}}
    </div>
  );
}}''',
        "tabs": f'''export function Tabs({{ tabs, activeTab, onChange, variant = "underline" }}) {{
  const base = "px-4 py-2 text-sm font-medium transition-colors duration-[120ms]";
  const styles = {{
    underline: {{ active: "border-b-2 border-[{primary}] text-[{primary}]", idle: "text-[{text_c}]/60 hover:text-[{text_c}] border-b-2 border-transparent" }},
    pill: {{ active: "bg-[{primary}] text-white rounded-full", idle: "text-[{text_c}]/60 hover:bg-[{surface}] rounded-full" }},
    enclosed: {{ active: "bg-[{surface}] border border-[{border}] border-b-0 rounded-t-lg text-[{text_c}]", idle: "text-[{text_c}]/60 hover:text-[{text_c}]" }},
  }};
  return (
    <div className="flex gap-1" role="tablist">
      {{tabs.map(t => <button key={{t.key}} role="tab" aria-selected={{t.key === activeTab}} onClick={{() => onChange(t.key)}} className={{`${{base}} ${{t.key === activeTab ? styles[variant].active : styles[variant].idle}} ${{t.disabled ? "opacity-50 cursor-not-allowed" : ""}}`}} disabled={{t.disabled}}>{{t.label}}</button>)}}
    </div>
  );
}}''',
        "nav": f'''export function Nav({{ items, variant = "horizontal" }}) {{
  const layouts = {{ horizontal: "flex items-center gap-6 h-16 px-6", vertical: "flex flex-col gap-1 py-4", sidebar: "flex flex-col gap-1 py-4 w-[260px] min-h-screen border-r border-[{border}]" }};
  return (
    <nav className={{`bg-[{surface}] text-[{text_c}] ${{layouts[variant]}}`}}>
      {{items.map((item, i) => <a key={{i}} href={{item.href}} className={{`px-3 py-2 rounded-md text-sm font-medium transition-colors duration-[120ms] hover:bg-[{primary}]/10 hover:text-[{primary}] ${{item.active ? "bg-[{primary}]/10 text-[{primary}]" : ""}}`}}>{{item.label}}</a>)}}
    </nav>
  );
}}''',
        "table": f'''export function Table({{ columns, rows, variant = "striped", size = "default" }}) {{
  const cellPad = {{ compact: "px-3 py-2 text-sm", default: "px-4 py-3", spacious: "px-6 py-4" }};
  return (
    <div className="overflow-x-auto rounded-lg border border-[{border}]">
      <table className="w-full text-left text-[{text_c}]">
        <thead className="bg-[{surface}] border-b border-[{border}]">
          <tr>{{columns.map((col, i) => <th key={{i}} className={{`${{cellPad[size]}} font-semibold text-sm`}}>{{col.label}}</th>)}}</tr>
        </thead>
        <tbody>
          {{rows.map((row, ri) => <tr key={{ri}} className={{`border-b border-[{border}] last:border-0 ${{variant === "striped" && ri % 2 ? "bg-[{surface}]/50" : ""}}`}}>{{columns.map((col, ci) => <td key={{ci}} className={{cellPad[size]}}>{{row[col.key]}}</td>)}}</tr>)}}
        </tbody>
      </table>
    </div>
  );
}}''',
    }
    return _react.get(name, f"// {name} component — apply tokens via Tailwind config")


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
        "shadow": _SHADOW_PAIRS["sm"]["rest"],
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
        "question": content.get("question", "What does this do?"),
        "question_label": content.get("question_label", "QUESTION"),
        "stat": content.get("stat", "94%"),
        "stat_label": content.get("stat_label", "ACCURACY"),
        "receipt_title": content.get("receipt_title", "Details"),
        "receipt_items": content.get("receipt_items", "<li>Item 1</li><li>Item 2</li>"),
        "cells": content.get("cells", "".join(f'<div style="padding:24px;background:{tokens.get("surface","#f9fafb")};border:1px solid {tokens.get("border","#e5e7eb")};border-radius:8px"><h3>Cell {i+1}</h3></div>' for i in range(6))),
        "stack_cards": content.get("stack_cards", ""),
    }

    matched = None
    for key in _LAYOUT_PATTERNS:
        if key in pattern:
            matched = key
            break
    if not matched:
        matched = list(_LAYOUT_PATTERNS.keys())[0]

    body_html = _LAYOUT_PATTERNS[matched].format(**t)

    motion_css = "\n".join(_ANIMATION_PRESETS.values())
    reduced_motion = "@media (prefers-reduced-motion: reduce) { *, *::before, *::after { animation-duration: 0.01ms !important; transition-duration: 0.01ms !important; } }"

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
:root{{--ease-mark:{_MOTION_TOKENS['easing']['mark']};--ease-page:{_MOTION_TOKENS['easing']['page']};--micro:{_MOTION_TOKENS['duration']['micro']}ms;--settle:{_MOTION_TOKENS['duration']['settle']}ms;--land:{_MOTION_TOKENS['duration']['land']}ms;--draw:{_MOTION_TOKENS['duration']['draw']}ms;--reveal:{_MOTION_TOKENS['duration']['reveal']}ms}}
{motion_css}
{reduced_motion}
</style>
</head>
<body>
{body_html}
</body>
</html>"""

    return {"html": html, "pattern": matched, "notes": f"Layout: {matched}, font: {heading_font}, motion: semantic timing tokens"}


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


# ── Tool: export_tokens ──

def tool_export_tokens(args: dict) -> dict:
    tokens = args.get("tokens", {})
    fmt = args.get("format", "css")
    exporters = {
        "css": _tokens_to_css,
        "tailwind": _tokens_to_tailwind,
        "figma": _tokens_to_figma,
        "style_dictionary": _tokens_to_style_dictionary,
    }
    exporter = exporters.get(fmt)
    if not exporter:
        return {"error": f"unknown format: {fmt}. Available: {', '.join(exporters.keys())}"}
    output = exporter(tokens)
    return {"format": fmt, "output": output, "size": len(output)}


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
    html = args.get("html", "")
    preset_name = args.get("preset")
    preset = _BRAND_PRESETS.get(preset_name) if preset_name else None
    issues = []

    _CONTRAST_PAIRS = [
        ("text", "background", 4.5, "AA text"),
        ("text", "surface", 4.5, "AA text on surface"),
        ("primary", "background", 3.0, "UI element"),
        ("primary", "surface", 3.0, "UI element on surface"),
        ("error", "background", 3.0, "error indicator"),
        ("success", "background", 3.0, "success indicator"),
        ("warning", "background", 3.0, "warning indicator"),
    ]
    for fg_key, bg_key, threshold, label in _CONTRAST_PAIRS:
        fg, bg = tokens.get(fg_key), tokens.get(bg_key)
        if fg and bg and _valid_hex(fg) and _valid_hex(bg):
            ratio = _contrast_ratio(fg, bg)
            if ratio < threshold:
                issues.append({"severity": "error", "rule": "contrast", "detail": f"{fg_key}/{bg_key} contrast {ratio}:1 fails {label} (need {threshold}:1)", "fix": f"Adjust {fg_key} or {bg_key} for {threshold}:1 minimum"})
            elif threshold >= 4.5 and ratio < 7.0:
                issues.append({"severity": "warning", "rule": "contrast-aaa", "detail": f"{fg_key}/{bg_key} contrast {ratio}:1 passes AA but fails AAA (7.0:1)"})

    if tokens.get("primary") and tokens.get("background"):
        for deficiency in ("protanopia", "deuteranopia", "tritanopia"):
            sim_p = _simulate_cvd(tokens["primary"], deficiency)
            sim_bg = _simulate_cvd(tokens["background"], deficiency)
            ratio = _contrast_ratio(sim_p, sim_bg)
            if ratio < 3.0:
                issues.append({"severity": "warning", "rule": "cvd", "detail": f"primary/background fails 3:1 under {deficiency} ({ratio}:1)", "fix": "Increase lightness/saturation difference between primary and background"})

    if tokens.get("primary") and tokens.get("secondary"):
        dist = _color_distance(tokens["primary"], tokens["secondary"])
        if dist < 40:
            issues.append({"severity": "warning", "rule": "color-distinction", "detail": f"primary/secondary too similar (distance={dist:.0f}, need >40)", "fix": "Increase hue or lightness separation"})

    if tokens.get("primary") and tokens.get("error"):
        dist = _color_distance(tokens["primary"], tokens["error"])
        if dist < 60:
            issues.append({"severity": "error", "rule": "color-confusion", "detail": f"primary and error too similar (distance={dist:.0f}) — users can't tell actions from errors", "fix": "Use a distinctly different hue for error"})

    spacing = tokens.get("spacing", [])
    if spacing and isinstance(spacing, list):
        for i in range(1, len(spacing)):
            if spacing[i] <= spacing[i - 1]:
                issues.append({"severity": "error", "rule": "spacing-monotonic", "detail": f"Spacing scale not monotonically increasing at index {i}: {spacing[i-1]} >= {spacing[i]}"})
                break
        if len(spacing) >= 3:
            ratios = [spacing[i] / spacing[i - 1] for i in range(1, len(spacing)) if spacing[i - 1] > 0]
            if ratios:
                avg_ratio = sum(ratios) / len(ratios)
                for i, r in enumerate(ratios):
                    if abs(r - avg_ratio) > avg_ratio * 0.6:
                        issues.append({"severity": "warning", "rule": "spacing-consistency", "detail": f"Spacing jump at index {i+1} ({spacing[i]}->{spacing[i+1]}) breaks the scale rhythm (ratio {r:.2f} vs avg {avg_ratio:.2f})"})
                        break

    type_scale = tokens.get("type_scale", {})
    if type_scale and isinstance(type_scale, dict):
        sizes = list(type_scale.values())
        for i in range(1, len(sizes)):
            if sizes[i] <= sizes[i - 1]:
                issues.append({"severity": "error", "rule": "type-scale-monotonic", "detail": f"Type scale not increasing: {sizes[i-1]}px >= {sizes[i]}px"})
                break
        if sizes:
            base = [s for s in sizes if 15 <= s <= 18]
            if not base:
                issues.append({"severity": "warning", "rule": "type-base-size", "detail": "No base size in 15-18px range — body text may be too small or too large"})
            if min(sizes) < 11:
                issues.append({"severity": "error", "rule": "type-minimum", "detail": f"Smallest type size {min(sizes)}px below 11px minimum — unreadable on most screens"})

    border_radius = tokens.get("border_radius", {})
    if border_radius and isinstance(border_radius, dict):
        vals = [v for v in border_radius.values() if isinstance(v, (int, float)) and v < 9999]
        if vals and max(vals) > 24:
            issues.append({"severity": "warning", "rule": "radius-excessive", "detail": f"Max border-radius {max(vals)}px is very large — may look inconsistent at small sizes"})

    for color_key in ("primary", "secondary", "accent", "text", "background", "surface", "border"):
        c = tokens.get(color_key)
        if c and isinstance(c, str) and not _valid_hex(c):
            issues.append({"severity": "error", "rule": "invalid-color", "detail": f"'{color_key}' value '{c}' is not a valid hex color"})

    durations = tokens.get("durations", {})
    if durations and isinstance(durations, dict):
        for name, ms in durations.items():
            if isinstance(ms, (int, float)):
                if ms > 2000:
                    issues.append({"severity": "error", "rule": "motion-duration", "detail": f"Animation '{name}' at {ms}ms exceeds 2000ms max", "fix": "Keep animations under 1000ms for responsiveness"})
                elif ms > 1000:
                    issues.append({"severity": "warning", "rule": "motion-duration", "detail": f"Animation '{name}' at {ms}ms is slow — consider reducing to under 1000ms"})

    if html:
        if '<img' in html and 'alt=' not in html:
            issues.append({"severity": "error", "rule": "img-alt", "detail": "Image(s) missing alt attribute", "fix": "Add descriptive alt text to all <img> elements"})
        if '<html' in html and 'lang=' not in html:
            issues.append({"severity": "warning", "rule": "html-lang", "detail": "Missing lang attribute on <html>", "fix": "Add lang='en' (or appropriate language) to <html>"})
        if '<a' in html and 'href="#"' in html:
            issues.append({"severity": "warning", "rule": "placeholder-links", "detail": "Placeholder href='#' links found — replace with real URLs before shipping"})
        if 'onclick' in html.lower() or 'onmouseover' in html.lower():
            issues.append({"severity": "warning", "rule": "inline-handlers", "detail": "Inline event handlers found — prefer addEventListener or framework bindings"})
        if 'animation' in html or 'transition' in html:
            if 'prefers-reduced-motion' not in html:
                issues.append({"severity": "warning", "rule": "motion-reduced", "detail": "CSS animations/transitions found but no prefers-reduced-motion media query", "fix": "Add @media (prefers-reduced-motion: reduce) to disable animations"})

    if preset:
        tc = preset.get("type_constraints", {})
        if tc.get("display_caps") is False and html:
            if 'text-transform:uppercase' in html.replace(" ", "").lower() or 'text-transform: uppercase' in html.lower():
                issues.append({"severity": "error", "rule": "brand-display-caps", "detail": f"Display text uses uppercase — {preset_name} preset forbids caps on display type", "fix": "Remove text-transform:uppercase from display elements"})
        if tc.get("display_letterspacing") is False and html:
            if 'letter-spacing' in html.lower():
                has_display_ls = False
                for tag in ("h1", "h2", "h3"):
                    if f"<{tag}" in html and "letter-spacing" in html:
                        has_display_ls = True
                if has_display_ls:
                    issues.append({"severity": "warning", "rule": "brand-display-letterspacing", "detail": f"{preset_name} preset discourages letter-spacing on display type"})

    shadows = tokens.get("shadows", {})
    if shadows and isinstance(shadows, dict):
        shadow_keys = [k for k in ("sm", "md", "lg", "xl") if k in shadows]
        if len(shadow_keys) >= 2:
            for i in range(1, len(shadow_keys)):
                s_prev = shadows[shadow_keys[i - 1]]
                s_curr = shadows[shadow_keys[i]]
                if isinstance(s_prev, str) and isinstance(s_curr, str):
                    if len(s_curr) < len(s_prev):
                        issues.append({"severity": "warning", "rule": "shadow-progression", "detail": f"Shadow '{shadow_keys[i]}' appears smaller than '{shadow_keys[i-1]}' — shadow scale should progress"})
                        break

    errors = sum(1 for i in issues if i["severity"] == "error")
    warnings = sum(1 for i in issues if i["severity"] == "warning")
    if not issues:
        issues.append({"severity": "pass", "rule": "all", "detail": "All checks passed"})

    return {
        "issues": issues,
        "summary": {"errors": errors, "warnings": warnings, "total": len(issues)},
        "score": "pass" if errors == 0 else "fail",
    }


# ── MCP Tool Registry ──

TOOLS = {
    "palette": {
        "description": "Generate a WCAG-aware color palette for a product context, or validate a supplied brand color against one.",
        "inputSchema": {"type": "object", "properties": {"context": {"type": "string", "description": "Product/brand context, e.g. 'fintech dark dashboard'"}, "seed_color": {"type": "string"}, "mode": {"type": "string", "enum": ["light", "dark", "both"], "default": "both"}, "count": {"type": "integer", "default": 3}}, "required": ["context"]},
        "handler": tool_palette,
    },
    "brand_guidelines": {
        "description": "Generate brand guidelines with voice, palette, typography, spacing, motion, shadows, color usage rules, and do/don't constraints. Supports brand presets: restrained, editorial, utilitarian, playful, technical.",
        "inputSchema": {"type": "object", "properties": {"product_description": {"type": "string"}, "tone": {"type": "string", "enum": ["editorial", "utilitarian", "playful", "technical", "restrained"], "default": "utilitarian"}, "preset": {"type": "string", "enum": ["restrained", "editorial", "utilitarian", "playful", "technical"], "description": "Brand personality preset (Paul Rand 'restrained', editorial, utilitarian, playful, technical)"}}, "required": ["product_description"]},
        "handler": tool_brand_guidelines,
    },
    "generate_design_system": {
        "description": "Generate a complete design system with palette, type scale, spacing, motion tokens, animation presets, shadow pairs, color usage rules, type constraints, component specs, accessibility rules, and multi-format token export (CSS, Tailwind, Figma, Style Dictionary).",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "description": "Product description, e.g. 'enterprise SaaS analytics dashboard'"}, "treatment": {"type": "string", "enum": ["editorial", "utilitarian", "playful", "technical", "restrained"], "default": "utilitarian"}, "preset": {"type": "string", "enum": ["restrained", "editorial", "utilitarian", "playful", "technical"], "description": "Brand personality preset"}, "theme_aware": {"type": "boolean", "default": True}, "seed_color": {"type": "string"}}, "required": ["query"]},
        "handler": tool_generate_design_system,
    },
    "create_component": {
        "description": "Generate a component specification (sizing, spacing, states, variants) with ready-to-use HTML/CSS or React/Tailwind markup. Uses semantic motion tokens.",
        "inputSchema": {"type": "object", "properties": {"component": {"type": "string", "description": "e.g. 'primary button', 'data table', 'pricing card'"}, "tokens": {"type": "object", "description": "Design tokens to apply"}, "framework": {"type": "string", "enum": ["html-css", "react-tailwind"], "default": "html-css"}}, "required": ["component"]},
        "handler": tool_create_component,
    },
    "compose_page": {
        "description": "Compose a full HTML page from a layout pattern (hero, dashboard, sidebar, pricing, feature_grid, footer, receipt_card, chat_thread, matrix_grid, card_stack) with semantic motion tokens and prefers-reduced-motion support.",
        "inputSchema": {"type": "object", "properties": {"pattern": {"type": "string", "description": "e.g. 'dashboard', 'hero', 'receipt_card', 'chat_thread', 'matrix_grid'"}, "tokens": {"type": "object"}, "content": {"type": "object", "description": "Copy/data to fill: title, subtitle, cta, main_content, question, stat, etc."}}, "required": ["pattern", "tokens"]},
        "handler": tool_compose_page,
    },
    "export": {
        "description": "Export generated design output as a file or push to a Compose-compatible host for a shareable preview URL.",
        "inputSchema": {"type": "object", "properties": {"content": {"type": "string"}, "content_type": {"type": "string", "enum": ["html", "css", "svg", "markdown", "json"]}, "target": {"type": "string", "enum": ["file", "compose_host"], "default": "file"}, "title": {"type": "string"}}, "required": ["content", "content_type"]},
        "handler": tool_export,
    },
    "export_tokens": {
        "description": "Export design tokens in multiple formats: CSS custom properties, Tailwind config, Figma Tokens JSON, or Style Dictionary JSON. All include motion tokens, shadow pairs, and animation presets.",
        "inputSchema": {"type": "object", "properties": {"tokens": {"type": "object", "description": "Design tokens (color roles, type_scale, spacing, heading_font, body_font)"}, "format": {"type": "string", "enum": ["css", "tailwind", "figma", "style_dictionary"], "default": "css"}}, "required": ["tokens"]},
        "handler": tool_export_tokens,
    },
    "render_visual": {
        "description": "Render a visual image via aivision — badges, charts, palette swatches, gradients, patterns, composites. Returns base64 PNG.",
        "inputSchema": {"type": "object", "properties": {"type": {"type": "string", "enum": ["solid", "gradient", "pattern", "badge", "chart_bar", "palette_swatch", "composite"], "description": "Image type to render"}, "width": {"type": "integer"}, "height": {"type": "integer"}, "text": {"type": "string"}, "color": {}, "start": {}, "end": {}, "values": {"type": "array"}, "labels": {"type": "array"}, "colors": {"type": "array"}, "save_path": {"type": "string"}}, "required": ["type"]},
        "handler": tool_render_visual,
    },
    "design_critique": {
        "description": "Enterprise design audit: 20+ rules covering WCAG contrast, CVD simulation, color distinction, motion duration/reduced-motion, shadow progression, type scale/constraints, brand preset enforcement, spacing rhythm, border radius, HTML accessibility. Supports brand preset validation.",
        "inputSchema": {"type": "object", "properties": {"tokens": {"type": "object", "description": "Design tokens: color roles, spacing array, type_scale, border_radius, durations, shadows"}, "html": {"type": "string", "description": "Optional HTML to audit"}, "preset": {"type": "string", "enum": ["restrained", "editorial", "utilitarian", "playful", "technical"], "description": "Brand preset to validate against"}}, "required": ["tokens"]},
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
        return {"jsonrpc": "2.0", "id": req_id, "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "composer-mcp", "version": "0.3.0"}, "capabilities": {"tools": {}}}}

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

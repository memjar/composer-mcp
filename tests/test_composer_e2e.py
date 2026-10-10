#!/usr/bin/env python3
"""E2E tests for composer-mcp v2."""

import json
import subprocess
import sys

SERVER = "server/composer_mcp.py"

def _call(method, params=None, req_id=1):
    msg = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params:
        msg["params"] = params
    proc = subprocess.run(
        [sys.executable, SERVER],
        input=json.dumps(msg) + "\n",
        capture_output=True, text=True, timeout=10,
        cwd=str(__import__("pathlib").Path(__file__).resolve().parent.parent),
    )
    for line in proc.stdout.strip().split("\n"):
        if line.strip():
            return json.loads(line)
    raise RuntimeError(f"no output: stderr={proc.stderr}")


def _tool_call(name, arguments=None):
    resp = _call("tools/call", {"name": name, "arguments": arguments or {}})
    assert "error" not in resp, resp
    text = resp["result"]["content"][0]["text"]
    return json.loads(text)


def test_initialize():
    resp = _call("initialize")
    info = resp["result"]["serverInfo"]
    assert info["name"] == "composer-mcp"
    assert info["version"] == "0.3.0"


def test_tools_list():
    resp = _call("tools/list")
    names = {t["name"] for t in resp["result"]["tools"]}
    expected = {"palette", "brand_guidelines", "generate_design_system", "create_component", "compose_page", "export", "export_tokens", "render_visual", "design_critique"}
    assert expected == names, f"missing: {expected - names}, extra: {names - expected}"


def test_palette_basic():
    r = _tool_call("palette", {"context": "fintech dashboard", "mode": "light", "count": 1})
    p = r["palettes"][0]
    assert p["mode"] == "light"
    assert all(k in p["roles"] for k in ("primary", "background", "text", "error", "success", "warning"))


def test_palette_seed_color():
    r = _tool_call("palette", {"context": "brand", "seed_color": "#e54340", "mode": "light", "count": 1})
    assert r["palettes"][0]["roles"]["primary"] == "#e54340"


def test_brand_guidelines():
    r = _tool_call("brand_guidelines", {"product_description": "developer analytics tool", "tone": "technical", "preset": "restrained"})
    assert "markdown" in r
    assert "restrained" in r["markdown"].lower() or "Restrained" in r["markdown"]
    assert r["preset"] == "restrained"
    assert "Motion" in r["markdown"]
    assert "Shadows" in r["markdown"]


def test_design_system_presets():
    for preset in ("restrained", "editorial", "utilitarian", "playful", "technical"):
        r = _tool_call("generate_design_system", {"query": "test app", "preset": preset})
        ds = r["design_system"]
        assert ds["preset"] == preset
        assert "motion" in ds
        assert "shadows" in ds
        assert "color_usage_rules" in ds
        assert "type_constraints" in ds
        assert "tokens_css" in r
        assert "tokens_tailwind" in r
        assert "tokens_figma" in r
        assert "tokens_style_dictionary" in r


def test_design_system_motion_tokens():
    r = _tool_call("generate_design_system", {"query": "test"})
    motion = r["design_system"]["motion"]
    assert "easing" in motion
    assert "duration" in motion
    assert motion["duration"]["micro"] == 120
    assert motion["duration"]["reveal"] == 520


def test_design_system_shadow_pairs():
    r = _tool_call("generate_design_system", {"query": "test"})
    shadows = r["design_system"]["shadows"]
    for size in ("sm", "md", "lg"):
        assert "rest" in shadows[size]
        assert "hover" in shadows[size]


def test_create_component_html():
    for comp in ("button", "card", "input", "badge", "toast", "avatar"):
        r = _tool_call("create_component", {"component": comp, "framework": "html-css"})
        assert r["component"] == comp
        assert "<" in r["markup"]


def test_create_component_react():
    for comp in ("button", "card", "input", "badge", "modal", "avatar", "toast", "tabs", "nav", "table"):
        r = _tool_call("create_component", {"component": comp, "framework": "react-tailwind"})
        assert r["component"] == comp
        assert "export" in r["markup"] or comp in r["markup"]


def test_compose_page_patterns():
    for pattern in ("hero", "dashboard", "sidebar", "receipt_card", "chat_thread", "matrix_grid"):
        r = _tool_call("compose_page", {"pattern": pattern, "tokens": {"primary": "#3b82f6", "background": "#ffffff", "text": "#111827", "surface": "#f9fafb", "border": "#e5e7eb"}})
        assert "html" in r
        assert "prefers-reduced-motion" in r["html"]
        assert "ease-mark" in r["html"] or "--ease-mark" in r["html"]


def test_export_tokens_css():
    tokens = {"color": {"primary": "#3b82f6", "background": "#ffffff"}, "type_scale": {"base": 16}, "spacing": [0, 4, 8]}
    r = _tool_call("export_tokens", {"tokens": tokens, "format": "css"})
    assert "--color-primary" in r["output"]
    assert "--ease-mark" in r["output"]
    assert "prefers-reduced-motion" in r["output"]
    assert "@keyframes" in r["output"]


def test_export_tokens_tailwind():
    tokens = {"color": {"primary": "#3b82f6"}}
    r = _tool_call("export_tokens", {"tokens": tokens, "format": "tailwind"})
    assert "module.exports" in r["output"]
    assert "transitionTimingFunction" in r["output"]


def test_export_tokens_figma():
    tokens = {"color": {"primary": "#3b82f6"}}
    r = _tool_call("export_tokens", {"tokens": tokens, "format": "figma"})
    parsed = json.loads(r["output"])
    assert "color/primary" in parsed
    assert "motion/micro" in parsed


def test_export_tokens_style_dictionary():
    tokens = {"color": {"primary": "#3b82f6"}}
    r = _tool_call("export_tokens", {"tokens": tokens, "format": "style_dictionary"})
    parsed = json.loads(r["output"])
    assert "color" in parsed
    assert "motion" in parsed
    assert "easing" in parsed["motion"]


def test_critique_good_tokens():
    r = _tool_call("design_critique", {"tokens": {"primary": "#1d4ed8", "background": "#ffffff", "text": "#111827", "surface": "#f9fafb", "border": "#e5e7eb", "error": "#dc2626", "success": "#16a34a", "warning": "#d97706"}})
    errors = [i for i in r["issues"] if i["severity"] == "error"]
    assert len(errors) == 0, f"unexpected errors: {errors}"
    assert r["score"] == "pass"


def test_critique_bad_contrast():
    r = _tool_call("design_critique", {"tokens": {"text": "#cccccc", "background": "#ffffff"}})
    issues = [i for i in r["issues"] if i["rule"] == "contrast"]
    assert len(issues) > 0


def test_critique_cvd():
    r = _tool_call("design_critique", {"tokens": {"primary": "#00ff00", "background": "#ffffff"}})
    cvd = [i for i in r["issues"] if i["rule"] == "cvd"]
    assert isinstance(cvd, list)


def test_critique_brand_preset():
    r = _tool_call("design_critique", {"tokens": {"primary": "#1d4ed8", "background": "#ffffff", "text": "#111827"}, "html": "<h1 style='text-transform:uppercase'>HELLO</h1>", "preset": "restrained"})
    brand = [i for i in r["issues"] if "brand" in i["rule"]]
    assert len(brand) > 0


def test_critique_motion_reduced():
    r = _tool_call("design_critique", {"tokens": {"primary": "#1d4ed8", "background": "#ffffff", "text": "#111827"}, "html": "<div style='animation: fade 1s'>x</div>"})
    motion = [i for i in r["issues"] if i["rule"] == "motion-reduced"]
    assert len(motion) > 0


def test_export_file():
    r = _tool_call("export", {"content": "test", "content_type": "html", "title": "test-export"})
    assert "path" in r


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])

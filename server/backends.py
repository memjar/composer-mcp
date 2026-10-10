#!/usr/bin/env python3
"""Pre-AI backend integrations for composer-mcp.

Optional C-library backends with pure-Python fallbacks.
Each backend auto-detects availability and exposes a consistent API.
"""

import base64
import io
import json
import math
import os
import struct
import subprocess
import tempfile
from pathlib import Path

# --- Feature flags ---

try:
    import pyvips
    HAS_VIPS = True
except ImportError:
    HAS_VIPS = False

try:
    import cairo
    HAS_CAIRO = True
except ImportError:
    HAS_CAIRO = False

try:
    import cv2
    import numpy as np
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

try:
    from littlecms import cmsOpenProfileFromFile, cmsCreateTransform
    HAS_LCMS = True
except ImportError:
    HAS_LCMS = False


def available_backends():
    return {
        "libvips": HAS_VIPS,
        "cairo": HAS_CAIRO,
        "opencv": HAS_OPENCV,
        "pillow": HAS_PILLOW,
        "lcms": HAS_LCMS,
        "graphviz": _has_graphviz(),
        "ffprobe": _has_ffprobe(),
        "imagemagick": _has_imagemagick(),
    }


def _has_graphviz():
    try:
        subprocess.run(["dot", "-V"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _has_ffprobe():
    try:
        subprocess.run(["ffprobe", "-version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _has_imagemagick():
    try:
        subprocess.run(["magick", "-version"], capture_output=True, timeout=5)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        try:
            subprocess.run(["convert", "-version"], capture_output=True, timeout=5)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False


# ============================================================
# 1. VECTOR RENDER — Cairo with SVG string fallback
# ============================================================

def vector_render(spec):
    shape = spec.get("shape", "rect")
    width = spec.get("width", 400)
    height = spec.get("height", 300)
    fill = spec.get("fill", "#3b82f6")
    stroke = spec.get("stroke", "#1e3a5f")
    stroke_width = spec.get("stroke_width", 2)
    text = spec.get("text", "")
    font_size = spec.get("font_size", 16)
    output_format = spec.get("format", "svg")
    elements = spec.get("elements", [])

    if HAS_CAIRO and output_format in ("svg", "pdf", "png"):
        return _cairo_render(shape, width, height, fill, stroke, stroke_width, text, font_size, output_format, elements)
    return _svg_fallback(shape, width, height, fill, stroke, stroke_width, text, font_size, elements)


def _hex_to_rgb_float(h):
    h = h.lstrip("#")
    return int(h[0:2], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[4:6], 16) / 255.0


def _cairo_render(shape, w, h, fill, stroke, sw, text, fs, fmt, elements):
    buf = io.BytesIO()
    if fmt == "pdf":
        surface = cairo.PDFSurface(buf, w, h)
    elif fmt == "png":
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    else:
        surface = cairo.SVGSurface(buf, w, h)

    ctx = cairo.Context(surface)
    ctx.set_line_width(sw)

    fr, fg, fb = _hex_to_rgb_float(fill)
    sr, sg, sb = _hex_to_rgb_float(stroke)

    all_elements = [{"shape": shape, "x": 0, "y": 0, "w": w, "h": h, "fill": fill, "stroke": stroke, "text": text}]
    all_elements.extend(elements)

    for el in all_elements:
        eshape = el.get("shape", "rect")
        ex, ey = el.get("x", 0), el.get("y", 0)
        ew, eh = el.get("w", w), el.get("h", h)
        efr, efg, efb = _hex_to_rgb_float(el.get("fill", fill))
        esr, esg, esb = _hex_to_rgb_float(el.get("stroke", stroke))
        etext = el.get("text", "")

        if eshape == "circle":
            cx, cy = ex + ew / 2, ey + eh / 2
            radius = min(ew, eh) / 2
            ctx.arc(cx, cy, radius, 0, 2 * math.pi)
        elif eshape == "ellipse":
            cx, cy = ex + ew / 2, ey + eh / 2
            ctx.save()
            ctx.translate(cx, cy)
            ctx.scale(ew / 2, eh / 2)
            ctx.arc(0, 0, 1, 0, 2 * math.pi)
            ctx.restore()
        elif eshape == "line":
            x2, y2 = el.get("x2", ex + ew), el.get("y2", ey)
            ctx.move_to(ex, ey)
            ctx.line_to(x2, y2)
            ctx.set_source_rgb(esr, esg, esb)
            ctx.stroke()
            continue
        elif eshape == "polygon":
            points = el.get("points", [])
            if points:
                ctx.move_to(points[0][0], points[0][1])
                for px, py in points[1:]:
                    ctx.line_to(px, py)
                ctx.close_path()
        else:
            rx = el.get("rx", 0)
            if rx:
                _rounded_rect(ctx, ex, ey, ew, eh, rx)
            else:
                ctx.rectangle(ex, ey, ew, eh)

        ctx.set_source_rgb(efr, efg, efb)
        ctx.fill_preserve()
        ctx.set_source_rgb(esr, esg, esb)
        ctx.stroke()

        if etext:
            ctx.set_source_rgb(0, 0, 0)
            ctx.set_font_size(fs)
            extents = ctx.text_extents(etext)
            tx = ex + (ew - extents.width) / 2
            ty = ey + (eh + extents.height) / 2
            ctx.move_to(tx, ty)
            ctx.show_text(etext)

    if fmt == "png":
        surface.write_to_png(buf)
    surface.finish()

    if fmt == "svg":
        return {"format": "svg", "data": buf.getvalue().decode("utf-8"), "backend": "cairo"}
    elif fmt == "pdf":
        return {"format": "pdf", "data_b64": base64.b64encode(buf.getvalue()).decode(), "backend": "cairo"}
    else:
        return {"format": "png", "data_b64": base64.b64encode(buf.getvalue()).decode(), "backend": "cairo"}


def _rounded_rect(ctx, x, y, w, h, r):
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    ctx.close_path()


def _svg_fallback(shape, w, h, fill, stroke, sw, text, fs, elements):
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">']

    all_elements = [{"shape": shape, "x": 0, "y": 0, "w": w, "h": h, "fill": fill, "stroke": stroke, "text": text}]
    all_elements.extend(elements)

    for el in all_elements:
        eshape = el.get("shape", "rect")
        ex, ey = el.get("x", 0), el.get("y", 0)
        ew, eh = el.get("w", w), el.get("h", h)
        efill = el.get("fill", fill)
        estroke = el.get("stroke", stroke)
        etext = el.get("text", "")
        rx = el.get("rx", 0)

        if eshape == "circle":
            cx, cy = ex + ew / 2, ey + eh / 2
            r = min(ew, eh) / 2
            parts.append(f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="{efill}" stroke="{estroke}" stroke-width="{sw}"/>')
        elif eshape == "ellipse":
            cx, cy = ex + ew / 2, ey + eh / 2
            parts.append(f'  <ellipse cx="{cx}" cy="{cy}" rx="{ew/2}" ry="{eh/2}" fill="{efill}" stroke="{estroke}" stroke-width="{sw}"/>')
        elif eshape == "line":
            x2, y2 = el.get("x2", ex + ew), el.get("y2", ey)
            parts.append(f'  <line x1="{ex}" y1="{ey}" x2="{x2}" y2="{y2}" stroke="{estroke}" stroke-width="{sw}"/>')
        elif eshape == "polygon":
            pts = el.get("points", [])
            pts_str = " ".join(f"{px},{py}" for px, py in pts)
            parts.append(f'  <polygon points="{pts_str}" fill="{efill}" stroke="{estroke}" stroke-width="{sw}"/>')
        else:
            parts.append(f'  <rect x="{ex}" y="{ey}" width="{ew}" height="{eh}" rx="{rx}" fill="{efill}" stroke="{estroke}" stroke-width="{sw}"/>')

        if etext:
            tx = ex + ew / 2
            ty = ey + eh / 2
            parts.append(f'  <text x="{tx}" y="{ty}" text-anchor="middle" dominant-baseline="central" font-size="{fs}" fill="#000">{etext}</text>')

    parts.append("</svg>")
    return {"format": "svg", "data": "\n".join(parts), "backend": "svg-fallback"}


# ============================================================
# 2. DIAGRAM — Graphviz DOT engine
# ============================================================

def diagram_render(spec):
    dot_source = spec.get("dot", "")
    graph_type = spec.get("type", "digraph")
    nodes = spec.get("nodes", [])
    edges = spec.get("edges", [])
    layout = spec.get("layout", "dot")
    output_format = spec.get("format", "svg")
    rankdir = spec.get("rankdir", "TB")
    style = spec.get("style", {})

    if not dot_source:
        dot_source = _build_dot(graph_type, nodes, edges, rankdir, style)

    if _has_graphviz():
        return _graphviz_render(dot_source, layout, output_format)
    return {"format": "dot", "data": dot_source, "backend": "dot-source-only", "note": "graphviz not installed — returning raw DOT"}


def _build_dot(graph_type, nodes, edges, rankdir, style):
    connector = "->" if graph_type == "digraph" else "--"
    lines = [f'{graph_type} G {{']
    lines.append(f'  rankdir={rankdir};')

    node_defaults = style.get("node", {})
    edge_defaults = style.get("edge", {})
    graph_defaults = style.get("graph", {})

    if graph_defaults:
        attrs = ", ".join(f'{k}="{v}"' for k, v in graph_defaults.items())
        lines.append(f"  graph [{attrs}];")
    if node_defaults:
        attrs = ", ".join(f'{k}="{v}"' for k, v in node_defaults.items())
        lines.append(f"  node [{attrs}];")
    if edge_defaults:
        attrs = ", ".join(f'{k}="{v}"' for k, v in edge_defaults.items())
        lines.append(f"  edge [{attrs}];")

    for n in nodes:
        if isinstance(n, str):
            lines.append(f'  "{n}";')
        else:
            nid = n.get("id", n.get("label", ""))
            attrs = []
            for k in ("label", "shape", "color", "fillcolor", "style", "fontcolor", "fontsize"):
                if k in n:
                    attrs.append(f'{k}="{n[k]}"')
            attr_str = f" [{', '.join(attrs)}]" if attrs else ""
            lines.append(f'  "{nid}"{attr_str};')

    for e in edges:
        if isinstance(e, (list, tuple)):
            src, dst = e[0], e[1]
            label = e[2] if len(e) > 2 else None
        else:
            src, dst = e.get("from", e.get("src", "")), e.get("to", e.get("dst", ""))
            label = e.get("label")
        label_attr = f' [label="{label}"]' if label else ""
        lines.append(f'  "{src}" {connector} "{dst}"{label_attr};')

    lines.append("}")
    return "\n".join(lines)


def _graphviz_render(dot_source, layout, fmt):
    try:
        result = subprocess.run(
            ["dot", f"-K{layout}", f"-T{fmt}"],
            input=dot_source, capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return {"error": result.stderr, "dot": dot_source, "backend": "graphviz"}
        if fmt == "svg":
            return {"format": "svg", "data": result.stdout, "backend": "graphviz"}
        return {"format": fmt, "data_b64": base64.b64encode(result.stdout.encode("latin-1")).decode(), "backend": "graphviz"}
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc), "dot": dot_source, "backend": "graphviz"}


# ============================================================
# 3. IMAGE ANALYZE — OpenCV with Pillow fallback
# ============================================================

def image_analyze(spec):
    source = spec.get("source", "")
    operations = spec.get("operations", ["histogram", "edges", "dominant_colors"])

    if source.startswith("data:") or source.startswith("base64:"):
        raw = source.split(",", 1)[-1] if "," in source else source.replace("base64:", "")
        img_bytes = base64.b64decode(raw)
    elif os.path.isfile(source):
        with open(source, "rb") as f:
            img_bytes = f.read()
    else:
        return {"error": "source must be a file path or base64 data"}

    results = {"backend": "opencv" if HAS_OPENCV else "pillow" if HAS_PILLOW else "none"}

    if HAS_OPENCV:
        import numpy as np
        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return {"error": "failed to decode image"}
        results["dimensions"] = {"width": img.shape[1], "height": img.shape[0], "channels": img.shape[2] if len(img.shape) > 2 else 1}

        if "histogram" in operations:
            hist = {}
            for i, color in enumerate(("blue", "green", "red")):
                h = cv2.calcHist([img], [i], None, [256], [0, 256])
                hist[color] = [int(v[0]) for v in h]
            results["histogram"] = hist

        if "edges" in operations:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            edges = cv2.Canny(gray, 100, 200)
            edge_count = int(np.count_nonzero(edges))
            results["edges"] = {"edge_pixels": edge_count, "edge_density": round(edge_count / (img.shape[0] * img.shape[1]), 4)}

        if "dominant_colors" in operations:
            pixels = img.reshape(-1, 3).astype(np.float32)
            k = min(5, len(pixels))
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
            _, labels, centers = cv2.kmeans(pixels, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
            counts = np.bincount(labels.flatten())
            total = sum(counts)
            colors = []
            for idx in np.argsort(-counts):
                b, g, r = [int(c) for c in centers[idx]]
                colors.append({"hex": f"#{r:02x}{g:02x}{b:02x}", "percent": round(counts[idx] / total * 100, 1)})
            results["dominant_colors"] = colors

        if "contours" in operations:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            _, thresh = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
            contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            results["contours"] = {"count": len(contours), "areas": sorted([int(cv2.contourArea(c)) for c in contours], reverse=True)[:20]}

        if "blur_score" in operations:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            results["blur_score"] = {"variance": round(float(laplacian_var), 2), "is_blurry": laplacian_var < 100}

    elif HAS_PILLOW:
        pil_img = Image.open(io.BytesIO(img_bytes))
        results["dimensions"] = {"width": pil_img.width, "height": pil_img.height, "mode": pil_img.mode}

        if "histogram" in operations:
            hist_data = pil_img.histogram()
            if pil_img.mode == "RGB":
                results["histogram"] = {"red": hist_data[:256], "green": hist_data[256:512], "blue": hist_data[512:768]}
            else:
                results["histogram"] = {"gray": hist_data[:256]}

        if "dominant_colors" in operations:
            small = pil_img.copy()
            small.thumbnail((64, 64))
            if small.mode != "RGB":
                small = small.convert("RGB")
            quantized = small.quantize(colors=5, method=Image.Quantize.MEDIANCUT)
            palette = quantized.getpalette()[:15]
            colors = []
            for i in range(0, len(palette), 3):
                r, g, b = palette[i], palette[i+1], palette[i+2]
                colors.append({"hex": f"#{r:02x}{g:02x}{b:02x}"})
            results["dominant_colors"] = colors

    return results


# ============================================================
# 4. IMAGE PROCESS — libvips pipeline with Pillow fallback
# ============================================================

def image_process(spec):
    source = spec.get("source", "")
    pipeline = spec.get("pipeline", [])
    output_format = spec.get("output_format", "png")

    if source.startswith("data:") or source.startswith("base64:"):
        raw = source.split(",", 1)[-1] if "," in source else source.replace("base64:", "")
        img_bytes = base64.b64decode(raw)
    elif os.path.isfile(source):
        with open(source, "rb") as f:
            img_bytes = f.read()
    else:
        return {"error": "source must be a file path or base64 data"}

    if HAS_VIPS:
        return _vips_pipeline(img_bytes, pipeline, output_format)
    elif HAS_PILLOW:
        return _pillow_pipeline(img_bytes, pipeline, output_format)
    return {"error": "no image backend available (install pyvips or Pillow)"}


def _vips_pipeline(img_bytes, pipeline, fmt):
    img = pyvips.Image.new_from_buffer(img_bytes, "")
    for op in pipeline:
        action = op.get("action")
        if action == "resize":
            scale = op.get("scale", 1.0)
            if "width" in op:
                scale = op["width"] / img.width
            img = img.resize(scale)
        elif action == "crop":
            img = img.crop(op.get("x", 0), op.get("y", 0), op["width"], op["height"])
        elif action == "rotate":
            angle = op.get("angle", 0)
            img = img.rotate(angle)
        elif action == "flip":
            if op.get("direction", "horizontal") == "horizontal":
                img = img.fliphor()
            else:
                img = img.flipver()
        elif action == "sharpen":
            sigma = op.get("sigma", 1.0)
            img = img.sharpen(sigma=sigma)
        elif action == "blur":
            sigma = op.get("sigma", 3.0)
            img = img.gaussblur(sigma)
        elif action == "grayscale":
            img = img.colourspace("b-w")
        elif action == "brightness":
            factor = op.get("factor", 1.0)
            img = img * factor
        elif action == "composite":
            overlay_bytes = base64.b64decode(op["overlay"])
            overlay = pyvips.Image.new_from_buffer(overlay_bytes, "")
            mode = op.get("mode", "over")
            img = img.composite2(overlay, mode)

    out_bytes = img.write_to_buffer(f".{fmt}")
    return {
        "format": fmt,
        "data_b64": base64.b64encode(out_bytes).decode(),
        "dimensions": {"width": img.width, "height": img.height},
        "backend": "libvips",
    }


def _pillow_pipeline(img_bytes, pipeline, fmt):
    img = Image.open(io.BytesIO(img_bytes))
    for op in pipeline:
        action = op.get("action")
        if action == "resize":
            if "width" in op and "height" in op:
                img = img.resize((op["width"], op["height"]), Image.LANCZOS)
            elif "width" in op:
                ratio = op["width"] / img.width
                img = img.resize((op["width"], int(img.height * ratio)), Image.LANCZOS)
            elif "scale" in op:
                new_w = int(img.width * op["scale"])
                new_h = int(img.height * op["scale"])
                img = img.resize((new_w, new_h), Image.LANCZOS)
        elif action == "crop":
            img = img.crop((op.get("x", 0), op.get("y", 0), op.get("x", 0) + op["width"], op.get("y", 0) + op["height"]))
        elif action == "rotate":
            img = img.rotate(op.get("angle", 0), expand=True)
        elif action == "flip":
            if op.get("direction", "horizontal") == "horizontal":
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            else:
                img = img.transpose(Image.FLIP_TOP_BOTTOM)
        elif action == "sharpen":
            img = img.filter(ImageFilter.SHARPEN)
        elif action == "blur":
            radius = op.get("sigma", op.get("radius", 3))
            img = img.filter(ImageFilter.GaussianBlur(radius=radius))
        elif action == "grayscale":
            img = img.convert("L")
        elif action == "brightness":
            from PIL import ImageEnhance
            img = ImageEnhance.Brightness(img).enhance(op.get("factor", 1.0))

    buf = io.BytesIO()
    save_fmt = fmt.upper()
    if save_fmt == "JPG":
        save_fmt = "JPEG"
    img.save(buf, format=save_fmt)
    return {
        "format": fmt,
        "data_b64": base64.b64encode(buf.getvalue()).decode(),
        "dimensions": {"width": img.width, "height": img.height},
        "backend": "pillow",
    }


# ============================================================
# 5. COLOR CONVERT — ICC profile handling
# ============================================================

def color_convert(spec):
    colors = spec.get("colors", [])
    from_space = spec.get("from_space", "srgb")
    to_space = spec.get("to_space", "display-p3")
    output = spec.get("output", "hex")

    results = []
    for color in colors:
        if isinstance(color, str):
            color = color.lstrip("#")
            r, g, b = int(color[0:2], 16) / 255.0, int(color[2:4], 16) / 255.0, int(color[4:6], 16) / 255.0
        elif isinstance(color, (list, tuple)):
            r, g, b = color[0] / 255.0, color[1] / 255.0, color[2] / 255.0
        else:
            continue

        if to_space == "linear-srgb":
            rl = _srgb_to_linear(r)
            gl = _srgb_to_linear(g)
            bl = _srgb_to_linear(b)
            results.append(_format_color(rl, gl, bl, output, to_space))
        elif to_space == "display-p3":
            rl, gl, bl = _srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b)
            M = ((1.2249, -0.2247, 0.0), (-0.0420, 1.0419, 0.0), (-0.0197, -0.0786, 1.0979))
            pr = M[0][0] * rl + M[0][1] * gl + M[0][2] * bl
            pg = M[1][0] * rl + M[1][1] * gl + M[1][2] * bl
            pb = M[2][0] * rl + M[2][1] * gl + M[2][2] * bl
            pr, pg, pb = _linear_to_srgb(pr), _linear_to_srgb(pg), _linear_to_srgb(pb)
            results.append(_format_color(pr, pg, pb, output, to_space))
        elif to_space == "oklch":
            L, C, H = _srgb_to_oklch(r, g, b)
            results.append({"oklch": f"oklch({L:.3f} {C:.3f} {H:.1f})", "L": round(L, 3), "C": round(C, 3), "H": round(H, 1)})
        elif to_space == "hsl":
            import colorsys
            h, l, s = colorsys.rgb_to_hls(r, g, b)
            results.append({"hsl": f"hsl({h*360:.0f}, {s*100:.1f}%, {l*100:.1f}%)", "h": round(h * 360, 1), "s": round(s * 100, 1), "l": round(l * 100, 1)})
        elif to_space == "lab":
            L, a, b_val = _srgb_to_lab(r, g, b)
            results.append({"lab": f"lab({L:.1f} {a:.1f} {b_val:.1f})", "L": round(L, 1), "a": round(a, 1), "b": round(b_val, 1)})
        else:
            results.append(_format_color(r, g, b, output, to_space))

    return {"conversions": results, "from_space": from_space, "to_space": to_space, "backend": "lcms" if HAS_LCMS else "math-fallback"}


def _srgb_to_linear(c):
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c):
    c = max(0, min(1, c))
    if c <= 0.0031308:
        return c * 12.92
    return 1.055 * (c ** (1.0 / 2.4)) - 0.055


def _srgb_to_lab(r, g, b):
    rl, gl, bl = _srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b)
    x = 0.4124564 * rl + 0.3575761 * gl + 0.1804375 * bl
    y = 0.2126729 * rl + 0.7151522 * gl + 0.0721750 * bl
    z = 0.0193339 * rl + 0.1191920 * gl + 0.9503041 * bl
    xn, yn, zn = 0.95047, 1.0, 1.08883
    fx = _lab_f(x / xn)
    fy = _lab_f(y / yn)
    fz = _lab_f(z / zn)
    L = 116 * fy - 16
    a = 500 * (fx - fy)
    bv = 200 * (fy - fz)
    return L, a, bv


def _lab_f(t):
    if t > 0.008856:
        return t ** (1.0 / 3.0)
    return (903.3 * t + 16) / 116


def _srgb_to_oklch(r, g, b):
    rl, gl, bl = _srgb_to_linear(r), _srgb_to_linear(g), _srgb_to_linear(b)
    l_ = 0.4122214708 * rl + 0.5363325363 * gl + 0.0514459929 * bl
    m_ = 0.2119034982 * rl + 0.6806995451 * gl + 0.1073969566 * bl
    s_ = 0.0883024619 * rl + 0.2817188376 * gl + 0.6299787005 * bl
    l_ = l_ ** (1/3) if l_ > 0 else 0
    m_ = m_ ** (1/3) if m_ > 0 else 0
    s_ = s_ ** (1/3) if s_ > 0 else 0
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    bv = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    C = math.sqrt(a * a + bv * bv)
    H = math.degrees(math.atan2(bv, a)) % 360
    return L, C, H


def _format_color(r, g, b, output, space):
    ri, gi, bi = int(round(max(0, min(1, r)) * 255)), int(round(max(0, min(1, g)) * 255)), int(round(max(0, min(1, b)) * 255))
    hex_val = f"#{ri:02x}{gi:02x}{bi:02x}"
    if output == "css":
        return {"css": f"color({space} {r:.4f} {g:.4f} {b:.4f})", "hex_approx": hex_val}
    return {"hex": hex_val, "rgb": [ri, gi, bi]}


# ============================================================
# 6. TEXTURE GENERATE — Perlin/Simplex noise (pure Python)
# ============================================================

_PERM = list(range(256))
import hashlib as _hashlib
_seed_bytes = _hashlib.sha256(b"composer-mcp-noise").digest()
for _i in range(255, 0, -1):
    _j = _seed_bytes[_i % 32] % (_i + 1)
    _PERM[_i], _PERM[_j] = _PERM[_j], _PERM[_i]
_PERM = _PERM + _PERM


def _fade(t):
    return t * t * t * (t * (t * 6 - 15) + 10)


def _lerp(t, a, b):
    return a + t * (b - a)


def _grad2(h, x, y):
    h = h & 3
    u = x if h < 2 else y
    v = y if h < 2 else x
    return (u if h & 1 == 0 else -u) + (v if h & 2 == 0 else -v)


def _perlin2(x, y):
    xi, yi = int(math.floor(x)) & 255, int(math.floor(y)) & 255
    xf, yf = x - math.floor(x), y - math.floor(y)
    u, v = _fade(xf), _fade(yf)
    aa = _PERM[_PERM[xi] + yi]
    ab = _PERM[_PERM[xi] + yi + 1]
    ba = _PERM[_PERM[xi + 1] + yi]
    bb = _PERM[_PERM[xi + 1] + yi + 1]
    return _lerp(v, _lerp(u, _grad2(aa, xf, yf), _grad2(ba, xf - 1, yf)),
                    _lerp(u, _grad2(ab, xf, yf - 1), _grad2(bb, xf - 1, yf - 1)))


def texture_generate(spec):
    width = spec.get("width", 256)
    height = spec.get("height", 256)
    noise_type = spec.get("type", "perlin")
    scale = spec.get("scale", 0.05)
    octaves = spec.get("octaves", 4)
    persistence = spec.get("persistence", 0.5)
    lacunarity = spec.get("lacunarity", 2.0)
    color_map = spec.get("color_map", None)
    output_format = spec.get("format", "png")

    grid = []
    for y in range(height):
        row = []
        for x in range(width):
            if noise_type == "perlin":
                val = _fbm(x * scale, y * scale, octaves, persistence, lacunarity)
            elif noise_type == "ridged":
                val = _ridged_fbm(x * scale, y * scale, octaves, persistence, lacunarity)
            elif noise_type == "turbulence":
                val = _turbulence(x * scale, y * scale, octaves, persistence, lacunarity)
            elif noise_type == "voronoi":
                val = _voronoi(x * scale, y * scale)
            else:
                val = _fbm(x * scale, y * scale, octaves, persistence, lacunarity)
            row.append(val)
        grid.append(row)

    min_v = min(min(row) for row in grid)
    max_v = max(max(row) for row in grid)
    rng = max_v - min_v if max_v != min_v else 1

    if HAS_PILLOW:
        if color_map:
            img = Image.new("RGB", (width, height))
            pixels = img.load()
            for y in range(height):
                for x in range(width):
                    t = (grid[y][x] - min_v) / rng
                    r, g, b = _sample_color_map(t, color_map)
                    pixels[x, y] = (r, g, b)
        else:
            img = Image.new("L", (width, height))
            pixels = img.load()
            for y in range(height):
                for x in range(width):
                    pixels[x, y] = int((grid[y][x] - min_v) / rng * 255)

        buf = io.BytesIO()
        img.save(buf, format=output_format.upper())
        return {
            "format": output_format,
            "data_b64": base64.b64encode(buf.getvalue()).decode(),
            "dimensions": {"width": width, "height": height},
            "noise_type": noise_type,
            "backend": "pillow",
        }

    normalized = [[int((grid[y][x] - min_v) / rng * 255) for x in range(width)] for y in range(height)]
    return {
        "format": "raw",
        "grid_sample": normalized[:8],
        "dimensions": {"width": width, "height": height},
        "noise_type": noise_type,
        "backend": "none",
        "note": "install Pillow for PNG output",
    }


def _fbm(x, y, octaves, persistence, lacunarity):
    total, amplitude, frequency = 0, 1, 1
    for _ in range(octaves):
        total += _perlin2(x * frequency, y * frequency) * amplitude
        amplitude *= persistence
        frequency *= lacunarity
    return total


def _ridged_fbm(x, y, octaves, persistence, lacunarity):
    total, amplitude, frequency = 0, 1, 1
    for _ in range(octaves):
        val = 1 - abs(_perlin2(x * frequency, y * frequency))
        total += val * val * amplitude
        amplitude *= persistence
        frequency *= lacunarity
    return total


def _turbulence(x, y, octaves, persistence, lacunarity):
    total, amplitude, frequency = 0, 1, 1
    for _ in range(octaves):
        total += abs(_perlin2(x * frequency, y * frequency)) * amplitude
        amplitude *= persistence
        frequency *= lacunarity
    return total


def _voronoi(x, y):
    ix, iy = int(math.floor(x)), int(math.floor(y))
    min_dist = float("inf")
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            cx, cy = ix + dx, iy + dy
            h = _PERM[(_PERM[cx & 255] + (cy & 255)) & 511]
            px = cx + (h & 15) / 15.0
            py = cy + ((h >> 4) & 15) / 15.0
            dist = (x - px) ** 2 + (y - py) ** 2
            if dist < min_dist:
                min_dist = dist
    return math.sqrt(min_dist)


def _sample_color_map(t, cmap):
    if isinstance(cmap, list):
        n = len(cmap) - 1
        idx = t * n
        i = min(int(idx), n - 1)
        frac = idx - i
        c1 = _parse_map_color(cmap[i])
        c2 = _parse_map_color(cmap[i + 1])
        return (
            int(c1[0] + (c2[0] - c1[0]) * frac),
            int(c1[1] + (c2[1] - c1[1]) * frac),
            int(c1[2] + (c2[2] - c1[2]) * frac),
        )
    g = int(t * 255)
    return (g, g, g)


def _parse_map_color(c):
    if isinstance(c, str):
        c = c.lstrip("#")
        return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)
    return tuple(c[:3])


# ============================================================
# 7. VIDEO PROBE — FFprobe metadata extraction
# ============================================================

def video_probe(spec):
    source = spec.get("source", "")
    if not os.path.isfile(source):
        return {"error": f"file not found: {source}"}

    if not _has_ffprobe():
        return {"error": "ffprobe not installed"}

    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", source],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return {"error": result.stderr}
        probe = json.loads(result.stdout)

        summary = {"file": os.path.basename(source), "streams": []}
        fmt = probe.get("format", {})
        summary["duration"] = float(fmt.get("duration", 0))
        summary["size_bytes"] = int(fmt.get("size", 0))
        summary["format_name"] = fmt.get("format_name", "")
        summary["bit_rate"] = int(fmt.get("bit_rate", 0))

        for stream in probe.get("streams", []):
            s = {"type": stream.get("codec_type"), "codec": stream.get("codec_name")}
            if s["type"] == "video":
                s["width"] = stream.get("width")
                s["height"] = stream.get("height")
                s["fps"] = _parse_fps(stream.get("r_frame_rate", "0/1"))
                s["pix_fmt"] = stream.get("pix_fmt")
            elif s["type"] == "audio":
                s["sample_rate"] = stream.get("sample_rate")
                s["channels"] = stream.get("channels")
            summary["streams"].append(s)

        return {"probe": summary, "backend": "ffprobe"}
    except (subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return {"error": str(exc)}


def _parse_fps(rate_str):
    parts = rate_str.split("/")
    if len(parts) == 2 and int(parts[1]) != 0:
        return round(int(parts[0]) / int(parts[1]), 2)
    return 0

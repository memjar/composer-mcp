# composer-mcp v0.4.0 Setup

## Quick Start

```bash
# Clone
git clone git@github.com:memjar/composer-mcp.git
cd composer-mcp

# Core deps
pip3 install Pillow httpx

# Optional backends (install what you need)
pip3 install pyvips pycairo opencv-python-headless

# CLI backends
brew install graphviz ffmpeg imagemagick
```

## MCP Config

Add to `~/.claude.json` under `mcpServers`:

```json
{
  "composer-mcp": {
    "command": "python3",
    "args": ["/path/to/composer-mcp/server/composer_mcp.py"]
  }
}
```

## 16 Tools

### Design System (v0.3.0)
| Tool | What |
|---|---|
| `palette` | WCAG-aware color palettes |
| `brand_guidelines` | Brand voice + typography + motion |
| `generate_design_system` | Complete design system with token export |
| `create_component` | HTML/CSS or React/Tailwind components |
| `compose_page` | Full HTML pages from layout patterns |
| `export` | File export or Compose host push |
| `export_tokens` | CSS/Tailwind/Figma/Style Dictionary tokens |
| `render_visual` | Badges, charts, swatches via aivision |
| `design_critique` | 20+ rule enterprise design audit |

### Pre-AI Backends (v0.4.0)
| Tool | Backend | Fallback |
|---|---|---|
| `backends` | — | Lists install status |
| `vector_render` | Cairo | Pure SVG string |
| `diagram` | Graphviz | Raw DOT source |
| `image_analyze` | OpenCV | Pillow |
| `image_process` | libvips | Pillow |
| `color_convert` | Little CMS | sRGB math |
| `texture_generate` | — | Pure Python Perlin |
| `video_probe` | FFprobe | — |

## Verify

```bash
python3 -m pytest tests/test_composer_e2e.py -v
# 35 tests should pass
```

Check backend status:
```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"backends","arguments":{}}}' | python3 server/composer_mcp.py
```

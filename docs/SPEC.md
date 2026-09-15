# Composer — Product Spec

## 1. Name check

"Composer" alone collides hard: Composer (PHP dependency manager), Adobe/Meta/Microsoft "Composer" products,
and countless music-composition apps. For an enterprise design MCP it needs a qualifier in the tagline and in
every listing/registry entry, even if the product name stays "Composer":

- Working name: **Composer** (product-first, AXE stays the maker in the background)
- Qualifier for listings/SEO: **"Composer — Design MCP"** or **"Composer for Design Systems"**
- Package/registry slug: `composer-design-mcp` (avoids collision in npm/PyPI/registry search; the spoken/marketing
  name stays "Composer")

This mirrors how the existing `memjar/compose` product already carries a generic, collision-prone name
("Compose" — AI-agnostic artifact platform). Composer is a distinct, narrower product: Compose is
plumbing (create/store/view any artifact), Composer is the **design craft layer** — it knows what a good
enterprise design system looks like and Compose (or any MCP client) is one place it can render to.

## 2. Positioning

**One-liner:** Composer is the design MCP any AI agent calls to produce on-brand, enterprise-grade design
output — palettes, type systems, components, and full page compositions — instead of guessing at CSS.

**Target buyer:**
- Enterprise design/brand teams who need agents to stay on-brand without a human designer reviewing every
  artifact (brand ops, design systems teams, internal tools teams).
- Agent builders / platform teams wiring design capability into their own agents via MCP, who don't want to
  build or maintain a design-token corpus themselves.

**Complements Illuminate/Lumen:** Illuminate and Lumen are *explainer* engines — they turn a topic or a live
process into a narrated, animated reel. Composer is a *design-system* engine — it produces the visual
language (palette, type, components, layout) that Illuminate/Lumen (and everything else) render inside.
Composer is upstream of them: an Illuminate reel or a Lumen spec can call Composer for its palette/typography
instead of hardcoding one, and Composer can call Compose (compose.casa) to host/preview what it produces.

## 3. What already exists (investigated before building)

- **`memjar/compose`** (compose.casa) — live Rust/Axum service, MCP at `compose.casa/mcp` with **7 tools**:
  `compose_create`, `compose_canvas`, `compose_list`, `compose_get`, `compose_search`, `compose_recall`,
  `compose_delete`. This is a generic artifact store + blob-URL viewer (like Claude/OpenAI artifacts) — it
  has no design *generation* logic, no palette/type/pattern knowledge. It's the hosting substrate, not the
  craft.
- **`axe-design-system`** — a real, separate backend (BM25-searchable corpus across 5 domains: palettes,
  typography, patterns, components, accessibility) already wired into the AXE gateway as 8 tools
  (`design_system`, `design_palette`, `design_typography`, `design_pattern`, `design_component`,
  `design_accessibility`, `design_search`, `design_status`). **Finding: currently broken** — `design_status`
  returns `{"available": false, "error": "No module named 'search'"}`, pointing at
  `~/Desktop/Desktop - JL1/axios/axe-design-system/packages/axe-design/scripts`, a path that doesn't resolve
  from this box. This is the single most valuable existing asset for Composer's substance and it needs a
  repair pass (see Open Decision below) before Composer can wrap it for real.
- **`artifact-design` skill** — Claude's own design methodology (palette formula + validator, type scale,
  layout heuristics, theme-aware light/dark tokens, editorial vs. utilitarian treatment). This is proven,
  portable design *judgment*, not a searchable corpus — good as the generation/critique layer Composer's
  tools call into when producing new output, complementary to axe-design-system's corpus lookups.
- **`~/.axe/repos/lumen`** — AI-agnostic, zero-dependency explainer engine (`lumen` CLI: new/from/narrate/
  render/serve/lint/make). Confirms the pattern Composer should follow: zero-dep core, AI-agnostic provider
  layer, CLI + spec file + player, no AXE-internal naming in the shipped artifact.

**Conclusion:** Composer is new — it doesn't exist yet as a product. It should be built as a thin, well-
designed MCP tool surface over (a) a repaired axe-design-system corpus for lookups and (b) generation logic
following the artifact-design methodology for synthesis, with Compose as an optional hosting/preview backend.

## 4. Tool surface

All tools are stateless design *generation/lookup* calls; nothing here stores artifacts — that's Compose's
job (Composer can optionally call out to a configured Compose-compatible host to render a preview).

### `palette`
Generate or retrieve an on-brand color palette.
```json
{
  "name": "palette",
  "description": "Generate a WCAG-aware color palette for a product context, or validate a supplied brand color against one.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "context": {"type": "string", "description": "Product/brand context, e.g. 'fintech dark dashboard'"},
      "seed_color": {"type": "string", "description": "Optional hex to anchor the palette to an existing brand color"},
      "mode": {"type": "string", "enum": ["light", "dark", "both"], "default": "both"},
      "count": {"type": "integer", "default": 3, "description": "Number of palette options to return"}
    },
    "required": ["context"]
  },
  "output": {
    "palettes": [{"name": "string", "roles": {"primary": "#hex", "secondary": "#hex", "accent": "#hex", "background": "#hex", "surface": "#hex", "text": "#hex", "border": "#hex"}, "contrast_report": "per-pair WCAG AA/AAA pass/fail"}]
  }
}
```

### `brand_guidelines`
Produce (or extend) a written brand guideline doc: voice, palette, type, logo usage rules, do/don't examples.
```json
{
  "name": "brand_guidelines",
  "description": "Generate a brand guidelines document (voice, palette, typography, spacing, do/don't rules) from a product description or an existing partial brand kit.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "product_description": {"type": "string"},
      "existing_kit": {"type": "object", "description": "Optional partial brand kit to extend (palette/type/logo already fixed)"},
      "tone": {"type": "string", "enum": ["editorial", "utilitarian", "playful", "technical"], "default": "utilitarian"}
    },
    "required": ["product_description"]
  },
  "output": {"markdown": "string", "tokens": {"color": {}, "type": {}, "spacing": {}}}
}
```

### `generate_design_system`
The umbrella tool: palette + typography + spacing scale + component states + accessibility rules in one call.
```json
{
  "name": "generate_design_system",
  "description": "Generate a complete design system (palette, type scale, spacing, component specs, accessibility rules) for a product context.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "query": {"type": "string", "description": "Product description, e.g. 'enterprise SaaS analytics dashboard, dark mode'"},
      "treatment": {"type": "string", "enum": ["editorial", "utilitarian"], "default": "utilitarian"},
      "theme_aware": {"type": "boolean", "default": true}
    },
    "required": ["query"]
  },
  "output": {"design_system": {"palette": {}, "typography": {}, "spacing": {}, "components": [], "accessibility": []}, "tokens_css": "string"}
}
```

### `create_component`
Single-component spec + markup for one UI element (button, card, nav, table, modal, badge...).
```json
{
  "name": "create_component",
  "description": "Get or generate a component specification (sizing, spacing, states, variants) with ready-to-use HTML/CSS.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "component": {"type": "string", "description": "e.g. 'primary button', 'data table', 'pricing card'"},
      "tokens": {"type": "object", "description": "Design tokens (from generate_design_system or palette) to apply"},
      "framework": {"type": "string", "enum": ["html-css", "react-tailwind"], "default": "html-css"}
    },
    "required": ["component"]
  },
  "output": {"spec": {"sizing": {}, "states": [], "variants": []}, "markup": "string"}
}
```

### `compose_page`
Full-page composition: applies a design system to a page-level layout pattern (hero, dashboard, pricing...).
```json
{
  "name": "compose_page",
  "description": "Compose a full page (HTML) from a layout pattern and a design system/tokens set.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "pattern": {"type": "string", "description": "e.g. 'dashboard sidebar', 'pricing table comparison', 'hero + feature grid'"},
      "tokens": {"type": "object"},
      "content": {"type": "object", "description": "Copy/data to fill the pattern"}
    },
    "required": ["pattern", "tokens"]
  },
  "output": {"html": "string", "notes": "string"}
}
```

### `export`
Ship the result somewhere: raw file, or push to a configured Compose-compatible host for a shareable preview URL.
```json
{
  "name": "export",
  "description": "Export generated design output as a file or push it to a Compose-compatible host for a shareable preview URL.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "content": {"type": "string"},
      "content_type": {"type": "string", "enum": ["html", "css", "svg", "markdown", "json"]},
      "target": {"type": "string", "enum": ["file", "compose_host"], "default": "file"},
      "title": {"type": "string"}
    },
    "required": ["content", "content_type"]
  },
  "output": {"path_or_url": "string"}
}
```

## 5. Architecture

- **Remote hosting:** `composer.axe.onl/mcp` — bearer-authed streamable-HTTP, matching the pattern already
  proven by `mcp.axe.onl/mcp` (axe-gateway, 1155 tools) and `compose.casa/mcp`. Domain choice: keep it under
  `axe.onl` (owned, already the MCP-hosting domain) rather than minting a new domain — cheaper to operate and
  consistent with `mcp.axe.onl`. A vanity alias (`composer.design` or similar) can be layered on later for
  marketing once the product proves out; do not block on acquiring a new domain for v1.
- **Auth model:** per-seat / enterprise API keys issued by AXE (Bearer token, same shape as the existing
  `mcp.axe.onl` gateway keys), **not** Anthropic OAuth — this must work for any MCP client (Claude, ChatGPT,
  Cursor, custom agents), not just Claude.ai connectors. Free tier: unauthenticated, rate-limited (mirrors
  Compose's anon/pro/api tiers: 10/1,000/10,000 per day).
- **Packaging:**
  - `@axe/composer-mcp` on npm — stdio variant for local/offline use, thin wrapper that proxies to the same
    generation logic as the remote server (or bundles a local copy of the design corpus for fully offline
    use).
  - PyPI mirror for Python-first agent stacks.
  - Listing in the official MCP registry (`registry.modelcontextprotocol.io`) once the remote server is live
    and stable — registry listing requires a working, publicly reachable server plus a signed server.json.
- **Backend split:** Composer server (generation/lookup logic, wraps a repaired axe-design-system corpus +
  artifact-design-derived synthesis rules) is independent of Compose (hosting/viewer). Composer's `export`
  tool is the only place the two touch — it POSTs to a Compose-compatible `/api/create` endpoint.

## 6. Build plan

**Phase 0 (this session):** Spec + minimal stdio scaffold with 2 working tools (`palette`, `brand_guidelines`)
proving the shape end to end, no corpus dependency (self-contained generation logic so it runs standalone
today). Committed here, not deployed.

**Phase 1 — smallest real milestone:** Repair `axe-design-system` (fix the `No module named 'search'` import
so `design_status` reports available, confirm the corpus counts) and wire Composer's `palette` /
`brand_guidelines` / `create_component` tools to call it instead of the placeholder logic in this scaffold.
Still stdio-only, still local.

**Phase 2:** Add `generate_design_system` and `compose_page` (the composition tools), stand up
`composer.axe.onl/mcp` as a remote streamable-HTTP server with bearer auth, wire `export` to
`compose.casa/mcp`'s `compose_create`.

**Phase 3:** Publish `@axe/composer-mcp` (npm) stdio package, PyPI mirror, submit to
`registry.modelcontextprotocol.io` and relevant connector directories (Claude, ChatGPT apps).

**Phase 4:** Per-seat/enterprise API keys, usage metering, enterprise pitch collateral, brand guideline import
(let an enterprise upload their existing brand kit so Composer's output matches it, not a generic AXE style).

## 7. Go-to-market

- **Registry + connector directory submission:** publish `server.json` per the MCP registry spec, verify the
  remote endpoint's `/mcp` responds to the registry's health probe, submit via
  `registry.modelcontextprotocol.io`'s publish flow; separately submit to Claude's and ChatGPT's connector
  directories once OAuth-optional API-key auth is confirmed compatible with each.
- **Enterprise pitch (3 sentences):** Every AI agent your teams run today generates its own guess at color,
  type, and layout — Composer gives them one shared, on-brand design system to call instead, so output stays
  consistent whether it came from a support bot, an internal tool, or a marketing agent. It plugs in as an
  MCP tool in minutes, works with any agent framework, and never sends your brand assets through a third
  party's training pipeline. Composer is the design system your agents already needed, built by AXE and
  proven on AXE's own enterprise work.

## 8. Open decision for James

**The entire product's substance depends on repairing `axe-design-system`.** Right now `design_status`
returns `{"available": false, "error": "No module named 'search'"}` — the real palette/typography/pattern/
component/accessibility corpus that would make Composer's output actually good (not generic placeholder
logic like the Phase 0 scaffold) is not currently callable. Before investing further in Composer, James needs
to decide: (a) repair axe-design-system first (small, bounded fix — likely a `sys.path`/import issue given
the path is under a synced "Desktop - JL1" mount), or (b) have Composer's Phase 1 build fresh generation logic
on the artifact-design methodology alone and treat axe-design-system as a later data source. Recommendation:
(a) — it's almost certainly a quick fix and throwing away an existing BM25 corpus across 5 design domains to
rebuild from scratch would be wasted work.

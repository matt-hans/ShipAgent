#!/usr/bin/env python3
"""
ShipAgent Architecture Diagram — System Navigation Philosophy
Auto-sized boxes, larger text, no overflow, accurate MCP routing.
"""

from PIL import Image, ImageDraw, ImageFont
import math
import os

W = 5400
H_MAX = 8400
img = Image.new("RGB", (W, H_MAX))
draw = ImageDraw.Draw(img)

FONTS = "/Users/matthewhans/.claude/plugins/cache/anthropic-agent-skills/example-skills/69c0b1a06741/skills/canvas-design/canvas-fonts"
OUT = "/Users/matthewhans/Desktop/Programming/ShipAgent/architecture-diagram"

# ── Palette ───────────────────────────────────────────────────────────────────
BG      = (12, 14, 20)
BG2     = (16, 18, 26)
C_AGENT = (255, 152, 75);     C_AGENT_D = (170, 100, 50);   C_AGENT_F = (55, 34, 20)
C_TOOLS = (100, 215, 155);    C_TOOLS_D = (62, 135, 92)
C_MCP   = (95, 175, 255);     C_MCP_D   = (58, 108, 165)
C_SVC   = (175, 135, 255);    C_SVC_D   = (110, 84, 165)
C_DATA  = (255, 200, 95);     C_DATA_D  = (165, 125, 60)
C_FE    = (255, 115, 155);    C_FE_D    = (165, 72, 98)
C_DESK  = (135, 200, 220);    C_DESK_D  = (84, 125, 138)
C_LINE  = (70, 78, 98)
C_TEXT  = (200, 205, 218)
C_DIM   = (130, 135, 155)
C_ACC   = (175, 180, 198)
C_BDR   = (42, 46, 60)
C_FAINT = (90, 96, 115)
C_MCP_A = (75, 145, 220)  # MCP routing arrow

# ── Fonts — larger body text ──────────────────────────────────────────────────
def lf(n, s):
    try: return ImageFont.truetype(os.path.join(FONTS, n), s)
    except: return ImageFont.load_default()

FT   = lf("BigShoulders-Bold.ttf", 96)
FS   = lf("InstrumentSans-Regular.ttf", 38)
FSB  = lf("InstrumentSans-Bold.ttf", 38)
FSS  = lf("InstrumentSans-Bold.ttf", 32)
FL   = lf("InstrumentSans-Regular.ttf", 26)
FM   = lf("GeistMono-Regular.ttf", 24)
FMS  = lf("GeistMono-Regular.ttf", 20)
FMB  = lf("GeistMono-Bold.ttf", 24)
FTH  = lf("Jura-Light.ttf", 26)
FAC  = lf("InstrumentSerif-Italic.ttf", 30)
FTY  = lf("GeistMono-Regular.ttf", 16)

# Node fonts
FNT  = lf("InstrumentSans-Bold.ttf", 30)       # Node title — bigger
FNB  = lf("InstrumentSans-Regular.ttf", 24)     # Node body — bigger
FNM  = lf("GeistMono-Regular.ttf", 22)          # Node mono accent
FLG  = lf("InstrumentSans-Regular.ttf", 24)
FWM  = lf("Jura-Light.ttf", 18)
FANN = lf("InstrumentSans-Regular.ttf", 20)

# Line height constants
TITLE_H = 56       # Title bar height (was 50)
BODY_TOP = 20      # Padding above first line (was 16)
LINE_H = 34        # Line spacing (was 30)
BLANK_H = 12       # Blank line (was 8)
BODY_BOT = 24      # Padding below last line (was 20)
BODY_LEFT = 26     # Left indent (was 22)

# ── Primitives ────────────────────────────────────────────────────────────────
def tw(t, f):
    b = f.getbbox(t); return b[2] - b[0]

def rr(x, y, w, h, r, fill=None, ol=None, ow=1):
    if fill: draw.rounded_rectangle([x,y,x+w,y+h], r, fill=fill)
    if ol:   draw.rounded_rectangle([x,y,x+w,y+h], r, outline=ol, width=ow)

def grid():
    for x in range(0, W, 48):
        a = 8 if x % 240 == 0 else 3
        draw.line([(x,0),(x,H_MAX)], fill=(BG[0]+a,BG[1]+a,BG[2]+a))
    for y in range(0, H_MAX, 48):
        a = 8 if y % 240 == 0 else 3
        draw.line([(0,y),(W,y)], fill=(BG[0]+a,BG[1]+a,BG[2]+a))

def zone_bg(y, h, shade=False):
    if shade:
        draw.rectangle([0, y, W, y+h], fill=BG2)

def calc_node_h(lines):
    """Calculate exact node height from line list — no overflow."""
    h = TITLE_H + BODY_TOP
    for line in lines:
        if isinstance(line, tuple):
            text = line[0]
        else:
            text = line
        if text == "":
            h += BLANK_H
        else:
            h += LINE_H
    h += BODY_BOT
    return h

def node(x, y, w, title, lines, c, cd, r=16):
    """Draw auto-height node. Returns (x, y, w, h) for positioning."""
    h = calc_node_h(lines)
    bg = (c[0]//16+BG[0], c[1]//16+BG[1], c[2]//16+BG[2])
    rr(x, y, w, h, r, fill=bg, ol=cd, ow=2)
    # Title bar
    tb = (c[0]//10+BG[0], c[1]//10+BG[1], c[2]//10+BG[2])
    draw.rounded_rectangle([x+1,y+1,x+w-1,y+TITLE_H+r], r, fill=tb)
    draw.rectangle([x+1,y+TITLE_H,x+w-1,y+TITLE_H+r], fill=tb)
    draw.line([(x+1,y+TITLE_H),(x+w-1,y+TITLE_H)], fill=cd, width=1)
    draw.ellipse([x+20,y+TITLE_H//2-7,x+34,y+TITLE_H//2+7], fill=c)
    draw.text((x+44, y+13), title, fill=c, font=FNT)
    # Lines
    iy = y + TITLE_H + BODY_TOP
    for line in lines:
        if isinstance(line, tuple):
            text, font, color = line
        else:
            text, font, color = line, FNB, C_DIM
        if text == "":
            iy += BLANK_H
            continue
        draw.text((x+BODY_LEFT, iy), text, fill=color, font=font)
        iy += LINE_H
    return h

def arrv(x, y1, y2, c=C_LINE, w=2, s=10):
    draw.line([(x,y1),(x,y2-s)], fill=c, width=w)
    draw.polygon([(x,y2),(x-s//2,y2-s),(x+s//2,y2-s)], fill=c)

def arrl(x1,y1,x2,y2,c=C_LINE,w=2,s=10):
    draw.line([(x1,y1),(x2,y2)], fill=c, width=w)
    dx,dy = x2-x1, y2-y1
    l = math.sqrt(dx*dx+dy*dy)
    if l == 0: return
    nx,ny = dx/l, dy/l; px,py = -ny, nx
    draw.polygon([(x2,y2),(x2-nx*s-px*s*.4,y2-ny*s-py*s*.4),(x2-nx*s+px*s*.4,y2-ny*s+py*s*.4)], fill=c)

def zlabel(x, y, text, c):
    draw.line([(x,y+18),(x+32,y+18)], fill=c, width=3)
    draw.text((x+42, y+2), text, fill=c, font=FSB)

def bdg(x, y, text, c):
    bw = tw(text, FTY) + 14
    bg = (c[0]//10+BG[0], c[1]//10+BG[1], c[2]//10+BG[2])
    rr(x,y,bw,24,5, fill=bg, ol=c, ow=1)
    draw.text((x+7, y+4), text, fill=c, font=FTY)

# ══════════════════════════════════════════════════════════════════════════════
# RENDER
# ══════════════════════════════════════════════════════════════════════════════
draw.rectangle([0,0,W,H_MAX], fill=BG)
grid()

M = 130
cx = W // 2
G = 42   # gap

# ── Title ─────────────────────────────────────────────────────────────────────
Y = 80
draw.line([(M,Y),(W-M,Y)], fill=C_BDR, width=1)
Y += 24
draw.text((M, Y), "SHIPAGENT", fill=C_TEXT, font=FT)
bdg(M + tw("SHIPAGENT", FT) + 24, Y+30, "v1.0", C_AGENT)
Y += 112
draw.text((M, Y), "AI-Native Shipping Automation Platform", fill=C_DIM, font=FS)
draw.text((W-M-tw("Architecture Overview",FTH), Y+6), "Architecture Overview", fill=C_DIM, font=FTH)
Y += 52
draw.line([(M,Y),(W-M,Y)], fill=C_BDR, width=1)
Y += 18
draw.text((M,Y), "Agent \u2192 Tools \u2192 MCP \u2192 Services", fill=C_AGENT_D, font=FAC)
draw.text((M+tw("Agent \u2192 Tools \u2192 MCP \u2192 Services",FAC)+18, Y+3),
    "\u2014 strict hierarchy, no bypass", fill=C_DIM, font=FTH)
Y += 54

# ══════════════════════════════════════════════════════════════════════════════
# L0: PRESENTATION
# ══════════════════════════════════════════════════════════════════════════════
nw3 = (W - 2*M - G*2) // 3
pres_lines = [
    "Native WebView host (Rust)",
    "PyInstaller sidecar, one-folder build",
    "Ed25519 signed auto-updater",
    ("OS-assigned port dispatch", FNB, C_ACC),
    "macOS code-signing + entitlements",
]
pres_h = calc_node_h(pres_lines)

zone_bg(Y, pres_h + 120, shade=True)
zlabel(M, Y, "PRESENTATION", C_FE)
Y += 58

h1 = node(M, Y, nw3, "Tauri v2 Desktop", pres_lines, C_DESK, C_DESK_D)

node(M+nw3+G, Y, nw3, "React + Vite + TypeScript", [
    "shadcn/ui components, Tailwind v4",
    "SSE streaming via useConversation",
    "Global state via useAppState context",
    ("CommandCenter: chat orchestration", FNB, C_ACC),
    "OnboardingWizard, SettingsFlyout",
], C_FE, C_FE_D)

node(M+(nw3+G)*2, Y, nw3, "Headless CLI", [
    "Typer + Rich console, httpx client",
    "Modes: submit, interact, daemon",
    "Auto-confirm engine for headless",
    ("Watchdog: hot-folder file watcher", FNB, C_ACC),
    "Conversational REPL mode",
], C_FE, C_FE_D)

Y += h1 + 20
arrv(cx, Y, Y+56, C_LINE, 3, 10)
draw.text((cx+14, Y+16), "REST + SSE", fill=C_DIM, font=FMS)
Y += 64

# ══════════════════════════════════════════════════════════════════════════════
# L1: API LAYER
# ══════════════════════════════════════════════════════════════════════════════
api_lines = [
    "REST + SSE endpoints, /api/v1/ prefix",
    "",
    ("Primary path: conversations.py", FNB, C_ACC),
    "Thin route handlers (no business logic)",
    "jobs, preview, labels, data_sources",
    "platforms, settings, contacts, commands",
    "Agent audit logging endpoints",
]
api_h = calc_node_h(api_lines)
zone_bg(Y, api_h + 110)
zlabel(M, Y, "API LAYER", C_SVC)
Y += 56

h2 = node(M, Y, nw3, "FastAPI Backend", api_lines, C_SVC, C_SVC_D)

node(M+nw3+G, Y, nw3, "Conversation SSE Flow", [
    "POST /conversations/ to create session",
    "POST /{id}/messages to send input",
    "GET  /{id}/stream for SSE events",
    "",
    ("SSE events:", FNB, C_ACC),
    "text_delta, tool_call, tool_result",
    "preview_card, progress, completion",
], C_SVC, C_SVC_D)

node(M+(nw3+G)*2, Y, nw3, "Security & Credentials", [
    "API key auth (HMAC timing-safe)",
    "Rate limiting: 10 req / 5 min / IP",
    "Key strength minimum: 32 chars",
    "",
    ("KeyringStore: macOS Keychain", FNB, C_ACC),
    "Env var fallback for CI",
    "SettingsService: AppSettings DB",
], C_SVC, C_SVC_D)

Y += h2 + 20
arrv(cx, Y, Y+58, C_AGENT_D, 3, 11)
draw.text((cx+14, Y+16), "AgentSessionManager", fill=C_AGENT_D, font=FMS)
Y += 66

# ══════════════════════════════════════════════════════════════════════════════
# L2: AGENT CORE
# ══════════════════════════════════════════════════════════════════════════════
agent_lines = [
    ("Sole LLM consumer. Sole orchestrator.", FNB, C_ACC),
    "",
    "Streams responses via process_message_stream()",
    "Cancels in-progress work via interrupt()",
    "Default model: Claude Haiku 4.5",
    "",
    ("Dynamic system prompt per-message:", FNB, C_ACC),
    "Identity, service codes, live schema, mode rules",
    "",
    "Self-correction: 3 Jinja2 mapping retries",
]
agent_h = calc_node_h(agent_lines)
zone_bg(Y, agent_h + 120, shade=True)
zlabel(M, Y, "AGENT CORE", C_AGENT)
Y += 56

oa_x = M + 200
oa_w = W - 2*M - 400

# Glow
for i in range(6, 0, -1):
    gc = (C_AGENT_F[0]+i*4, C_AGENT_F[1]+i*3, C_AGENT_F[2]+i*2)
    rr(oa_x-i*3, Y-i*3, oa_w+i*6, agent_h+i*6, 20, ol=gc, ow=1)

h3 = node(oa_x, Y, oa_w, "OrchestrationAgent  \u2014  Claude Agent SDK",
    agent_lines, C_AGENT, C_AGENT_D)

# Left: Safety
sx = M
draw.text((sx, Y+14), "Safety Model", fill=C_AGENT, font=FL)
blocks = [
    ("Structural", ["Tool registry filtering", "Session isolation"]),
    ("Behavioral", ["Hooks block unsafe ops", "Audit all tool calls"]),
    ("Procedural", ["Mandatory preview step", "confirmJob() only path"]),
]
by = Y + 48
for label, items in blocks:
    draw.text((sx, by), label, fill=C_DIM, font=FANN)
    for j, t in enumerate(items):
        draw.text((sx+4, by+24+j*22), t, fill=C_FAINT, font=FANN)
    by += 24 + len(items)*22 + 10

# Right: Hooks
hx = oa_x + oa_w + 28
draw.text((hx, Y+14), "Hook System", fill=C_AGENT, font=FL)
draw.text((hx, Y+48), "PreToolUse gates:", fill=C_DIM, font=FANN)
for i, h in enumerate(["Block create_shipment", "Gate pickup scheduling", "Gate pickup cancel", "Force orchestrator track"]):
    draw.text((hx+4, Y+72+i*22), h, fill=C_FAINT, font=FANN)
draw.text((hx, Y+168), "PostToolUse:", fill=C_DIM, font=FANN)
for i, h in enumerate(["Audit log all calls", "Detect error responses"]):
    draw.text((hx+4, Y+192+i*22), h, fill=C_FAINT, font=FANN)

Y += h3 + 20

# Fan arrows
local_cx = M + (W-2*M)//4
mcp_cx = M + 3*(W-2*M)//4
arrl(cx, Y, local_cx, Y+52, C_TOOLS_D, 2, 9)
arrl(cx, Y, mcp_cx, Y+52, C_MCP_D, 2, 9)
draw.text((local_cx - 60, Y+14), "local tools", fill=C_TOOLS_D, font=FMS)
draw.text((mcp_cx - 80, Y+14), "MCP pass-through", fill=C_MCP_D, font=FMS)
Y += 60

# ══════════════════════════════════════════════════════════════════════════════
# L3: TOOL LAYER — split local vs MCP-backed
# ══════════════════════════════════════════════════════════════════════════════
local_lines = [
    ("data.py — Data source operations", FNM, C_ACC),
    "Queries data via DataSourceMCPClient",
    "get_source_info, get_schema, fetch_rows",
    "validate_filter_syntax, connect_shopify",
    "",
    ("pipeline.py — Batch shipping workflow", FNM, C_ACC),
    "ship_command_pipeline (fast path)",
    "create_job, add_rows, preview, execute",
    ("Also calls UPSMCPClient for rate/create", FNB, C_MCP_A),
    "",
    ("contacts.py — Address book (local DB)", FNM, C_ACC),
    "@handle resolution for agent use",
]
mcp_tool_lines = [
    ("pickup.py — All 6 pickup operations", FNM, C_ACC),
    "schedule, cancel, rate, status",
    "political_divisions, facilities",
    ("Each calls _get_ups_client() \u2192 UPSMCPClient", FNB, C_MCP_A),
    "",
    ("documents.py — Paperless customs", FNM, C_ACC),
    "upload, push, delete trade documents",
    "",
    ("tracking.py — Package tracking", FNM, C_ACC),
    "track_package with mismatch detection",
    "",
    ("interactive.py — Single shipment", FNM, C_ACC),
    ("Creates shipment via UPSMCPClient", FNB, C_MCP_A),
]

local_h = calc_node_h(local_lines)
mcp_h = calc_node_h(mcp_tool_lines)
tool_h = max(local_h, mcp_h)

zone_bg(Y, tool_h + 120)
zlabel(M, Y, "TOOL LAYER", C_TOOLS)

# Sub-labels
sub_x = M + 42 + tw("TOOL LAYER", FSB) + 24
draw.text((sub_x, Y+6), "Local execution", fill=C_TOOLS_D, font=FL)
draw.text((sub_x + tw("Local execution", FL) + 16, Y+6), "|", fill=C_BDR, font=FL)
draw.text((sub_x + tw("Local execution", FL) + 28, Y+6),
    "MCP-backed (thin wrappers \u2192 UPSMCPClient)", fill=C_MCP_D, font=FL)
Y += 56

half = (W - 2*M - G) // 2
mcp_bx = M + half + G

node(M, Y, half, "Local Tools", local_lines, C_TOOLS, C_TOOLS_D)
node(mcp_bx, Y, half, "MCP-Backed Tools  (UPS pass-through)", mcp_tool_lines, C_MCP, C_MCP_D)

Y += tool_h + 10

# Mode bar
draw.text((M, Y), "Batch:", fill=C_TOOLS_D, font=FMS)
draw.text((M+65, Y), "all tools exposed", fill=C_TOOLS, font=FMS)
draw.text((M+380, Y), "Interactive:", fill=C_TOOLS_D, font=FMS)
draw.text((M+500, Y), "status + preview_interactive + V2 MCP-backed tools", fill=C_TOOLS, font=FMS)
Y += 34

# ── Routing arrows from tools to lower layers ────────────────────────────────
data_cx = M + half//3
ups_cx = cx + 100
svc_cx_arrow = M + 2*half//3 + half

arrl(M + half//2, Y, data_cx, Y+56, C_MCP_D, 2, 9)
arrl(mcp_bx + half//2, Y, ups_cx, Y+56, C_MCP_A, 3, 10)
arrl(M + half - 40, Y, svc_cx_arrow, Y+56, C_SVC_D, 2, 9)

draw.text((data_cx - 90, Y+14), "DataSourceMCPClient", fill=C_MCP_D, font=FMS)
draw.text((ups_cx - 50, Y+14), "UPSMCPClient", fill=C_MCP_A, font=FMS)
draw.text((svc_cx_arrow - 40, Y+14), "direct call", fill=C_SVC_D, font=FMS)
Y += 64

# ══════════════════════════════════════════════════════════════════════════════
# L4: MCP CONNECTIVITY + EXECUTION SERVICES
# ══════════════════════════════════════════════════════════════════════════════
mcp_col_w = (W - 2*M - 48) // 2
svx = W//2 + 36

# Calculate heights
data_mcp_lines = [
    "Transport: stdio, process-global singleton",
    "Adapters: CSV, Excel, JSON, XML, EDI",
    ("Tools: import, schema, query, writeback", FNB, C_ACC),
    "Gateway: DataSourceMCPClient singleton",
    "Used by data.py, pipeline.py tools",
]
ups_mcp_lines = [
    "Transport: stdio, per-session or per-job",
    "",
    ("Shipping: rate, create, void, recover", FNB, C_ACC),
    ("Address: validate, track, transit-time", FNB, C_ACC),
    ("Pickup: schedule, cancel, rate, status", FNB, C_ACC),
    ("Locator, Paperless, Landed Cost", FNB, C_ACC),
    "",
    "Client: UPSMCPClient with retry + backoff",
]
ext_mcp_lines = [
    "Transport: stdio, process-global singleton",
    "Shopify, WooCommerce, SAP, Oracle",
    ("Normalizes all to ExternalOrder model", FNB, C_ACC),
    "Auto-reconnect after backend restart",
]
batch_lines = [
    "Unified preview + execution pipeline",
    "Concurrent: asyncio.gather + semaphore (5)",
    ("Per-row state writes for crash recovery", FNB, C_ACC),
    "SSE events for real-time progress",
    ("Routes through UPSMCPClient for UPS", FNB, C_MCP_A),
]
payload_lines = [
    "UPSPayloadBuilder: mapped data \u2192 UPS API",
    "",
    ("ups_constants.py", FNM, C_DATA),
    "Field limits, packaging codes, defaults",
    ("ups_service_codes.py", FNM, C_DATA),
    "ServiceCode enum with 40+ aliases",
    ("international_rules.py", FNM, C_DATA),
    "Lane-driven compliance rules",
]
core_svc_lines = [
    "JobService: state machine + row tracking",
    "AuditService: structured logging, redaction",
    ("DecisionAuditService: agent ledger", FNB, C_ACC),
    "ContactService: address book, @handle",
]

data_h = calc_node_h(data_mcp_lines)
ups_h = calc_node_h(ups_mcp_lines)
ext_h = calc_node_h(ext_mcp_lines)
batch_h = calc_node_h(batch_lines)
payload_h = calc_node_h(payload_lines)
core_h = calc_node_h(core_svc_lines)

# Total MCP column height
mcp_total = data_h + 16 + ups_h + 16 + ext_h
zone_bg(Y, mcp_total + 120, shade=True)
zlabel(M, Y, "MCP CONNECTIVITY", C_MCP)
zlabel(svx, Y, "EXECUTION SERVICES", C_SVC)
Y += 56

# Row 1: Data MCP + BatchEngine
node(M, Y, mcp_col_w, "Data Source MCP  (FastMCP + DuckDB)", data_mcp_lines, C_MCP, C_MCP_D)
node(svx, Y, mcp_col_w, "BatchEngine", batch_lines, C_SVC, C_SVC_D)

# BatchEngine → UPS MCP elbow arrow
be_bot = Y + batch_h
ups_y = Y + data_h + 16
ups_mid = ups_y + ups_h // 2

draw.line([(svx + 24, be_bot), (svx + 24, ups_mid)], fill=C_MCP_A, width=2)
draw.line([(svx + 24, ups_mid), (M + mcp_col_w + 8, ups_mid)], fill=C_MCP_A, width=2)
arrl(M + mcp_col_w + 30, ups_mid, M + mcp_col_w + 4, ups_mid, C_MCP_A, 2, 9)
draw.text((svx + 32, be_bot + 6), "UPSMCPClient", fill=C_MCP_A, font=FMS)

Y += data_h + 16

# Row 2: UPS MCP + Payload Builder — UPS MCP gets emphasis
for i in range(3, 0, -1):
    gc = (C_MCP_D[0]//4+i*2, C_MCP_D[1]//4+i*2, C_MCP_D[2]//4+i*2)
    rr(M-i*2, Y-i*2, mcp_col_w+i*4, ups_h+i*4, 18, ol=gc, ow=1)

node(M, Y, mcp_col_w, "UPS MCP Server  (local fork, 18 tools)", ups_mcp_lines, C_MCP, C_MCP_D)
node(svx, Y, mcp_col_w, "Payload Builder + Constants", payload_lines, C_DATA, C_DATA_D)

Y += max(ups_h, payload_h) + 16

# Row 3: External Sources + Core Services
node(M, Y, mcp_col_w, "External Sources MCP  (FastMCP)", ext_mcp_lines, C_MCP, C_MCP_D)
node(svx, Y, mcp_col_w, "Core Services", core_svc_lines, C_SVC, C_SVC_D)

Y += max(ext_h, core_h) + 22
arrv(cx, Y, Y+50, C_DATA_D, 3, 10)
Y += 58

# ══════════════════════════════════════════════════════════════════════════════
# L5: PERSISTENCE
# ══════════════════════════════════════════════════════════════════════════════
persist_lines = [
    "Job, JobRow, AuditLog",
    "ConversationSession + Message",
    "SavedDataSource, AppSettings",
    "",
    ("Timestamps: ISO8601 strings", FNB, C_ACC),
    ("Currency: integers in cents", FNB, C_ACC),
    "Enums inherit str + Enum (JSON safe)",
]
persist_h = calc_node_h(persist_lines)
zone_bg(Y, persist_h + 110)
zlabel(M, Y, "PERSISTENCE", C_DATA)
Y += 56

node(M, Y, nw3, "SQLite + SQLAlchemy", persist_lines, C_DATA, C_DATA_D)

node(M+nw3+G, Y, nw3, "DuckDB (in-memory analytics)", [
    "Analytical engine for Data Source MCP",
    "SQL generation via sqlglot library",
    "",
    ("Jinja2 logistics filter library:", FNB, C_ACC),
    "truncate_address, format_us_zip",
    "convert_weight, and more",
], C_DATA, C_DATA_D)

node(M+(nw3+G)*2, Y, nw3, "File System", [
    "Shipping labels stored on disk",
    "Referenced via JobRow.label_path",
    "Audit JSONL mirror log",
    "",
    ("platformdirs for production paths", FNB, C_ACC),
    "Dev fallback path resolution",
], C_DATA, C_DATA_D)

Y += persist_h + 34

# ══════════════════════════════════════════════════════════════════════════════
# LEGENDS
# ══════════════════════════════════════════════════════════════════════════════
draw.line([(M,Y),(W-M,Y)], fill=C_BDR, width=1)
Y += 22

# Error + Layer taxonomy
draw.text((M, Y), "Error Taxonomy", fill=C_ACC, font=FSS)
draw.text((W//2+36, Y), "Layer Taxonomy", fill=C_ACC, font=FSS)
Y += 42

errors = [("E-1xxx","Data",C_DATA),("E-2xxx","Validation",C_TOOLS),("E-3xxx","UPS API",C_MCP),
          ("E-4xxx","System",C_SVC),("E-5xxx","Auth",C_FE)]
ex = M
for code,desc,c in errors:
    draw.text((ex,Y), code, fill=c, font=FMB)
    draw.text((ex+95,Y), desc, fill=C_DIM, font=FL)
    ex += 220

layers = [(C_AGENT,"Intelligence"),(C_TOOLS,"Local Tools"),(C_MCP,"MCP-backed"),
          (C_SVC,"Services"),(C_DATA,"Data"),(C_FE,"Presentation"),(C_DESK,"Desktop")]
lx = W//2 + 36
for c,n in layers:
    draw.ellipse([lx,Y+6,lx+14,Y+20], fill=c)
    draw.text((lx+22,Y+1), n, fill=C_DIM, font=FLG)
    lx += tw(n, FLG) + 46

Y += 44

# Data flow
draw.text((M, Y), "Data Flow", fill=C_ACC, font=FSS)
Y += 40
flow = [("User",C_FE),(" \u2192 ",C_LINE),("Browser",C_FE),(" \u2192 ",C_LINE),("FastAPI",C_SVC),
        (" \u2192 ",C_LINE),("SessionMgr",C_AGENT_D),(" \u2192 ",C_LINE),("Agent",C_AGENT),
        (" \u2192 ",C_LINE),("Tools",C_TOOLS),(" \u2192 ",C_LINE),("MCP / Services",C_MCP)]
fx = M
for t,c in flow:
    draw.text((fx,Y), t, fill=c, font=FM); fx += tw(t,FM)+4

Y += 36
draw.text((M,Y), "Batch:", fill=C_DIM, font=FMS)
draw.text((M+65,Y),
    "pipeline \u2192 create_job \u2192 preview \u2192 confirmJob() \u2192 BatchEngine \u2192 UPSMCPClient \u2192 MCP \u2192 labels",
    fill=C_TOOLS_D, font=FMS)
Y += 26
draw.text((M,Y), "Interactive:", fill=C_DIM, font=FMS)
draw.text((M+120,Y),
    "preview_interactive \u2192 confirm \u2192 _get_ups_client() \u2192 UPSMCPClient \u2192 UPS MCP",
    fill=C_TOOLS_D, font=FMS)
Y += 26
draw.text((M,Y), "V2 Tools:", fill=C_DIM, font=FMS)
draw.text((M+100,Y),
    "pickup/tracking/docs \u2192 _get_ups_client() \u2192 UPSMCPClient \u2192 UPS MCP  (thin pass-through)",
    fill=C_MCP_A, font=FMS)

Y += 40

# Invariants
draw.line([(M,Y),(W-M,Y)], fill=C_BDR, width=1)
Y += 20
draw.text((M,Y), "Agent Design Invariants", fill=C_AGENT, font=FSS)
Y += 40

invs = [
    "1  No business logic in API routes",
    "2  No direct UPS calls outside MCP",
    "3  No LLM calls outside the agent",
    "4  No tool skips approval gates",
    "5  No mutable MCP client state",
    "6  No mode leakage between agents",
    "7  No row data in LLM context",
    "8  No scattered data definitions",
]
iw = (W - 2*M) // 4
for i, inv in enumerate(invs):
    ix = M + (i%4)*iw
    iy = Y + (i//4)*32
    draw.text((ix, iy), inv[:1], fill=C_AGENT_D, font=FMS)
    draw.text((ix+18, iy), inv[3:], fill=C_DIM, font=FMS)

Y += 32*2 + 30

# Footer
draw.line([(M,Y),(W-M,Y)], fill=C_BDR, width=1)
Y += 14
draw.text((M,Y), "SHIPAGENT ARCHITECTURE", fill=(60,65,80), font=FWM)
draw.text((cx-tw("Agent \u2192 Tools \u2192 MCP \u2192 Services",FWM)//2, Y),
    "Agent \u2192 Tools \u2192 MCP \u2192 Services", fill=C_AGENT_D, font=FWM)
draw.text((W-M-tw("System Navigation \u00b7 2026",FWM), Y),
    "System Navigation \u00b7 2026", fill=(60,65,80), font=FWM)
Y += 32

# ══════════════════════════════════════════════════════════════════════════════
# CROP & SAVE
# ══════════════════════════════════════════════════════════════════════════════
final_h = Y + 16
img_out = img.crop((0, 0, W, final_h))
out = os.path.join(OUT, "ShipAgent-Architecture.png")
img_out.save(out, "PNG", dpi=(300, 300))
print(f"Saved: {out}")
print(f"Size: {W}x{final_h} px @ 300 DPI = {W/300:.1f}x{final_h/300:.1f} in")

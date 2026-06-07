"""
App – FastAPI Orchestrator
============================
Serves the dashboard UI, handles WebSocket connections for real-time logs,
and exposes endpoints to trigger Playwright automation.
"""

import asyncio
import json
import time
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request
from playwright.async_api import async_playwright, Page

import llm_engine

# ─── Paths ────────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).parent
DEFAULT_ORIGIN_URL = "https://www.saucedemo.com/"

# ─── WebSocket Connection Manager ─────────────────────────────────────────────────

class ConnectionManager:
    """Manages active WebSocket connections for broadcasting logs."""

    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        self.active.remove(ws)

    async def broadcast(self, message: dict):
        for ws in self.active[:]:
            try:
                await ws.send_json(message)
            except Exception:
                self.active.remove(ws)


manager = ConnectionManager()


async def emit_log(msg: str, level: str = "info"):
    """Broadcast a log message to all connected dashboard clients."""
    await manager.broadcast({
        "type": "log",
        "level": level,
        "message": msg,
        "timestamp": time.time(),
    })


async def emit_metrics():
    """Broadcast current token metrics to all connected clients."""
    await manager.broadcast({
        "type": "metrics",
        "data": llm_engine.tracker.to_dict(),
    })


# ─── State ────────────────────────────────────────────────────────────────────────
state = {
    "browser": None,
    "context": None,
    "origin_page": None,
    "dest_page": None,
    "mapping": None,
    "successful_mappings": 0,
    "total_fields_attempted": 0,
}


# ─── Lifespan ─────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Cleanup browser on shutdown
    if state["browser"]:
        await state["browser"].close()


# ─── FastAPI App ──────────────────────────────────────────────────────────────────
app = FastAPI(title="AI Data Replicator Dashboard", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# ─── Routes ───────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard.html")


@app.get("/api/metrics")
async def get_metrics():
    """Return current token usage metrics."""
    return {
        **llm_engine.tracker.to_dict(),
        "successful_mappings": state["successful_mappings"],
        "total_fields_attempted": state["total_fields_attempted"],
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)


# ─── JavaScript Injection ─────────────────────────────────────────────────────────
ORIGIN_RECORDER_JS = """
(() => {
    window.__recorder_log = window.__recorder_log || [];
    document.addEventListener('copy', () => {
        const sel = window.getSelection().toString().trim();
        if (sel) {
            window.__recorder_log.push({
                type: 'copy', value: sel, timestamp: Date.now(),
                context: document.activeElement?.closest('[class]')?.className || ''
            });
        }
    });
    document.addEventListener('click', (e) => {
        const el = e.target;
        const text = el.innerText?.trim().substring(0, 200);
        if (text) {
            window.__recorder_log.push({
                type: 'click', value: text,
                selector: el.tagName + (el.id ? '#' + el.id : '') + (el.className ? '.' + el.className.split(' ')[0] : ''),
                timestamp: Date.now()
            });
        }
    });
})();
"""

DEST_RECORDER_JS = """
(() => {
    window.__recorder_log = window.__recorder_log || [];
    document.addEventListener('input', (e) => {
        const el = e.target;
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
            window.__recorder_log.push({
                type: 'input', field_id: el.id || null, field_name: el.name || null,
                label: el.closest('.form-group')?.querySelector('label')?.innerText || '',
                value: el.value, timestamp: Date.now()
            });
        }
    });
    document.addEventListener('paste', (e) => {
        const el = e.target;
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
            const pasted = (e.clipboardData || window.clipboardData).getData('text');
            window.__recorder_log.push({
                type: 'paste', field_id: el.id || null, field_name: el.name || null,
                label: el.closest('.form-group')?.querySelector('label')?.innerText || '',
                value: pasted, timestamp: Date.now()
            });
        }
    });
})();
"""


# ─── Dynamic Destination Form Builder ─────────────────────────────────────────────
def build_dest_html(fields: list[dict]) -> str:
    """Generate a dynamic destination form HTML from a list of field definitions."""
    rows = []
    for f in fields:
        fid = f.get("id", f.get("name", "")).replace(" ", "_").lower()
        label = f.get("label", fid)
        ftype = f.get("type", "text")
        tag = f.get("tag", "input")
        if tag == "textarea":
            rows.append(f'<div class="form-group"><label for="{fid}">{label}</label>'
                        f'<textarea id="{fid}" name="{fid}" rows="2" placeholder="{label}"></textarea></div>')
        else:
            rows.append(f'<div class="form-group"><label for="{fid}">{label}</label>'
                        f'<input type="{ftype}" id="{fid}" name="{fid}" placeholder="{label}"></div>')
    form_body = "\n".join(rows)
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<title>System B - Dynamic Destination</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: 'Segoe UI', sans-serif; background: #f0f4f8; padding: 40px; color: #333; }}
.container {{ max-width: 600px; margin: 0 auto; background: #fff; border-radius: 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.08); padding: 40px; }}
h1 {{ text-align: center; margin-bottom: 8px; color: #1a365d; font-size: 1.6rem; }}
.subtitle {{ text-align: center; color: #718096; margin-bottom: 32px; font-size: 0.9rem; }}
.form-group {{ margin-bottom: 20px; }}
label {{ display: block; margin-bottom: 6px; font-weight: 600; color: #2d3748; font-size: 0.9rem; }}
input, textarea {{ width: 100%; padding: 10px 14px; border: 2px solid #e2e8f0; border-radius: 8px; font-size: 1rem; }}
input:focus, textarea:focus {{ outline: none; border-color: #4299e1; }}
button {{ width: 100%; padding: 14px; background: #2b6cb0; color: #fff; border: none; border-radius: 8px; font-size: 1rem; font-weight: 600; cursor: pointer; margin-top: 12px; }}
.success-msg {{ display: none; text-align: center; padding: 16px; background: #c6f6d5; color: #276749; border-radius: 8px; margin-top: 16px; }}
</style></head><body>
<div class="container">
<h1>Dynamic Destination Portal</h1>
<p class="subtitle">System B &mdash; AI-Generated Form</p>
<form id="order-form">
{form_body}
<button type="submit">Submit Record</button>
</form>
<div class="success-msg" id="success-msg">Record saved!</div>
</div>
<script>
document.getElementById('order-form').addEventListener('submit', function(e) {{
    e.preventDefault();
    document.getElementById('success-msg').style.display = 'block';
    setTimeout(() => {{ document.getElementById('success-msg').style.display = 'none'; }}, 3000);
}});
</script></body></html>"""


# ─── Automation Endpoints ─────────────────────────────────────────────────────────
@app.post("/api/launch-browser")
async def launch_browser(request: Request):
    """Phase 1: Launch browser with two tabs. Accepts custom origin_url."""
    # Close existing browser if any
    if state["browser"]:
        try:
            await state["browser"].close()
        except Exception:
            pass
        state["browser"] = None
        state["origin_page"] = None
        state["dest_page"] = None
        state["mapping"] = None

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    origin_url = body.get("origin_url", DEFAULT_ORIGIN_URL)

    await emit_log("Launching Playwright browser...", "info")

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False)
    context = await browser.new_context()

    origin_page = await context.new_page()
    dest_page = await context.new_page()

    await emit_log(f"Opening Origin ({origin_url})...", "info")
    await origin_page.goto(origin_url, wait_until="domcontentloaded")

    dest_file = BASE_DIR / "destination_mock.html"
    dest_url = f"file://{dest_file.resolve()}"
    await emit_log("Opening Destination (System B)...", "info")
    await dest_page.goto(dest_url, wait_until="domcontentloaded")

    # Inject recorders
    await origin_page.evaluate(ORIGIN_RECORDER_JS)
    await dest_page.evaluate(DEST_RECORDER_JS)

    state["browser"] = browser
    state["context"] = context
    state["origin_page"] = origin_page
    state["dest_page"] = dest_page
    state["origin_url"] = origin_url

    await emit_log("Browser ready. Two tabs open with recorders injected.", "success")
    return {"status": "ok", "message": "Browser launched with two tabs"}


@app.post("/api/observe")
async def observe():
    """Phase 2: Collect interaction logs and infer mapping via LLM."""
    origin_page = state["origin_page"]
    dest_page = state["dest_page"]

    if not origin_page or not dest_page:
        return {"status": "error", "message": "Browser not launched. Call /api/launch-browser first."}

    await emit_log("Collecting interaction logs from both tabs...", "info")

    origin_log = await origin_page.evaluate("window.__recorder_log || []")
    dest_log = await dest_page.evaluate("window.__recorder_log || []")
    dest_fields = await dest_page.evaluate("""
        Array.from(document.querySelectorAll('input, textarea')).map(el => ({
            id: el.id, name: el.name,
            label: el.closest('.form-group')?.querySelector('label')?.innerText || '',
            type: el.type, tag: el.tagName.toLowerCase()
        }))
    """)

    await emit_log(f"Captured {len(origin_log)} origin events, {len(dest_log)} destination events.", "info")
    await emit_log("Sending interaction data to Gemini for mapping inference...", "info")

    # Call LLM engine
    result = await llm_engine.infer_mapping(origin_log, dest_log, dest_fields)
    mapping = result["mapping"]
    usage = result["usage"]

    state["mapping"] = mapping

    await emit_log(
        f"Mapping inferred! {len(mapping)} fields mapped. "
        f"Tokens: {usage['total_tokens']} | Cost: ${usage['estimated_cost']:.6f} | "
        f"Latency: {usage['latency_ms']:.0f}ms",
        "success"
    )

    # Log individual mappings
    for key, val in mapping.items():
        await emit_log(f"  Mapped '{key}' → {val.get('destination_selector', '?')}", "info")

    await emit_metrics()

    return {
        "status": "ok",
        "mapping": mapping,
        "usage": usage,
    }


@app.post("/api/automate")
async def automate():
    """Phase 3: Scrape origin, generate payload via LLM, fill destination."""
    origin_page = state["origin_page"]
    dest_page = state["dest_page"]
    mapping = state["mapping"]

    if not mapping:
        return {"status": "error", "message": "No mapping available. Run /api/observe first."}

    await emit_log("Scraping current state of origin page...", "info")

    # Scrape origin page data — generic DOM extraction (works on any site)
    page_data = await origin_page.evaluate("""
    (() => {
        const data = {};
        // Grab all meaningful text elements
        document.querySelectorAll(
            'h1, h2, h3, h4, h5, p, span, td, th, li, label, a, strong, b, em, ' +
            '[data-test], [data-testid], [class*="price"], [class*="name"], [class*="title"], ' +
            '[class*="total"], [class*="cost"], [class*="amount"], [class*="item"], [class*="product"]'
        ).forEach(el => {
            const text = el.innerText?.trim();
            if (text && text.length > 0 && text.length < 500) {
                const key = el.getAttribute('data-test') || el.getAttribute('data-testid')
                    || el.id || el.className?.split(' ')[0] || el.tagName;
                if (!data[key]) data[key] = text;
            }
        });
        // Grab input/select/textarea values
        document.querySelectorAll('input, select, textarea').forEach(el => {
            const key = el.id || el.name || el.getAttribute('aria-label') || el.placeholder || el.type;
            if (el.value) data['input_' + key] = el.value;
        });
        // Grab table data
        document.querySelectorAll('table').forEach((table, ti) => {
            table.querySelectorAll('tr').forEach((row, ri) => {
                const cells = Array.from(row.querySelectorAll('td, th')).map(c => c.innerText?.trim());
                if (cells.length > 0) data['table' + ti + '_row' + ri] = cells.join(' | ');
            });
        });
        // Full page text as fallback context
        data['_page_text'] = document.body.innerText.substring(0, 4000);
        return data;
    })()
    """)

    await emit_log(f"Scraped {len(page_data)} data points. Asking Gemini for fill payload...", "info")

    # Generate fill payload
    result = await llm_engine.generate_fill_payload(page_data, mapping)
    payload = result["payload"]
    usage = result["usage"]

    await emit_log(
        f"Payload generated! {len(payload)} fields to fill. "
        f"Tokens: {usage['total_tokens']} | Cost: ${usage['estimated_cost']:.6f}",
        "success"
    )

    # Fill the destination form
    await emit_log("Filling destination form...", "info")
    filled = 0
    failed = 0

    for selector, value in payload.items():
        try:
            await dest_page.fill(selector, str(value))
            await emit_log(f"  ✓ {selector} = \"{value}\"", "success")
            filled += 1
        except Exception as e:
            await emit_log(f"  ✗ {selector} failed: {e}", "error")
            failed += 1

    state["successful_mappings"] += filled
    state["total_fields_attempted"] += filled + failed

    await emit_log(
        f"Automation complete! {filled}/{filled + failed} fields filled successfully.",
        "success"
    )
    await emit_metrics()

    return {
        "status": "ok",
        "filled": filled,
        "failed": failed,
        "payload": payload,
        "usage": usage,
    }


@app.post("/api/reset-logs")
async def reset_logs():
    """Clear interaction logs in both tabs for a fresh observation."""
    if state["origin_page"]:
        await state["origin_page"].evaluate("window.__recorder_log = [];")
    if state["dest_page"]:
        await state["dest_page"].evaluate("window.__recorder_log = [];")
    await emit_log("Interaction logs cleared.", "info")
    return {"status": "ok"}


# ─── Entry Point ──────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)

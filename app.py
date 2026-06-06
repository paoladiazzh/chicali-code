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
DEST_FILE = BASE_DIR / "destination_mock.html"
ORIGIN_URL = "https://www.saucedemo.com/"

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


# ─── Automation Endpoints ─────────────────────────────────────────────────────────
@app.post("/api/launch-browser")
async def launch_browser():
    """Phase 1: Launch browser with two tabs."""
    await emit_log("Launching Playwright browser...", "info")

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False)
    context = await browser.new_context()

    origin_page = await context.new_page()
    dest_page = await context.new_page()

    await emit_log("Opening Origin (saucedemo.com)...", "info")
    await origin_page.goto(ORIGIN_URL, wait_until="domcontentloaded")

    dest_url = f"file://{DEST_FILE.resolve()}"
    await emit_log("Opening Destination (Order Ingestion Portal)...", "info")
    await dest_page.goto(dest_url, wait_until="domcontentloaded")

    # Inject recorders
    await origin_page.evaluate(ORIGIN_RECORDER_JS)
    await dest_page.evaluate(DEST_RECORDER_JS)

    state["browser"] = browser
    state["context"] = context
    state["origin_page"] = origin_page
    state["dest_page"] = dest_page

    await emit_log("Browser ready. Two tabs open with interaction recorders injected.", "success")
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

    # Scrape origin page data
    page_data = await origin_page.evaluate("""
    (() => {
        const data = {};
        const textEls = document.querySelectorAll(
            '.inventory_details_name, .inventory_details_desc, .inventory_details_price, ' +
            '.cart_item_label, .inventory_item_name, .inventory_item_price, .inventory_item_desc, ' +
            '.summary_value_label, .summary_subtotal_label, .summary_tax_label, .summary_total_label, ' +
            'h3, h2, .title, [data-test]'
        );
        textEls.forEach(el => {
            const key = el.className || el.getAttribute('data-test') || el.tagName;
            const val = el.innerText?.trim();
            if (val) data[key] = val;
        });
        document.querySelectorAll('input').forEach(el => {
            if (el.value) data[el.id || el.name || el.placeholder] = el.value;
        });
        data['_page_text'] = document.body.innerText.substring(0, 3000);
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

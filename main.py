"""
Autonomous Web Data Replicator
==============================
An AI agent that learns data-entry mappings by observing a user,
then replicates the process autonomously using an LLM for inference.

Phases:
  1. Connection  – Launch browser with two tabs (Origin & Destination).
  2. Observation – Record user interactions, infer field mapping via LLM.
  3. Automation  – Scrape new data from Origin, fill Destination autonomously.
"""

import asyncio
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from playwright.async_api import async_playwright, Page

load_dotenv()

# ─── Gemini Client (via OpenAI-compatible endpoint) ──────────────────────────────
client = AsyncOpenAI(
    api_key=os.getenv("GEMINI_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
)
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

ORIGIN_URL = "https://www.saucedemo.com/"
DEST_FILE = Path(__file__).parent / "destination_mock.html"


# ─── JavaScript Injection: Interaction Recorder ──────────────────────────────────
ORIGIN_RECORDER_JS = """
(() => {
    window.__recorder_log = window.__recorder_log || [];

    // Track text selections (copy actions)
    document.addEventListener('copy', () => {
        const sel = window.getSelection().toString().trim();
        if (sel) {
            window.__recorder_log.push({
                type: 'copy',
                value: sel,
                timestamp: Date.now(),
                context: document.activeElement?.closest('[class]')?.className || ''
            });
        }
    });

    // Track clicks on elements with text content
    document.addEventListener('click', (e) => {
        const el = e.target;
        const text = el.innerText?.trim().substring(0, 200);
        if (text) {
            window.__recorder_log.push({
                type: 'click',
                value: text,
                selector: el.tagName + (el.id ? '#' + el.id : '') + (el.className ? '.' + el.className.split(' ')[0] : ''),
                timestamp: Date.now()
            });
        }
    });

    console.log('[Recorder] Origin interaction tracking active.');
})();
"""

DEST_RECORDER_JS = """
(() => {
    window.__recorder_log = window.__recorder_log || [];

    // Track input/paste events on form fields
    document.addEventListener('input', (e) => {
        const el = e.target;
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
            window.__recorder_log.push({
                type: 'input',
                field_id: el.id || null,
                field_name: el.name || null,
                label: el.closest('.form-group')?.querySelector('label')?.innerText || '',
                value: el.value,
                timestamp: Date.now()
            });
        }
    });

    document.addEventListener('paste', (e) => {
        const el = e.target;
        if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
            const pasted = (e.clipboardData || window.clipboardData).getData('text');
            window.__recorder_log.push({
                type: 'paste',
                field_id: el.id || null,
                field_name: el.name || null,
                label: el.closest('.form-group')?.querySelector('label')?.innerText || '',
                value: pasted,
                timestamp: Date.now()
            });
        }
    });

    console.log('[Recorder] Destination interaction tracking active.');
})();
"""


# ─── Helper: Call LLM ────────────────────────────────────────────────────────────
async def call_llm(system_prompt: str, user_prompt: str) -> str:
    """Send a prompt to the Azure OpenAI deployment and return the response."""
    response = await client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=2000,
    )
    return response.choices[0].message.content.strip()


# ─── Phase 1 & 2: Connection & Observation ───────────────────────────────────────
async def observe(origin_page: Page, dest_page: Page) -> dict:
    """
    Inject recorders, wait for user demonstration, then ask the LLM
    to infer field mappings from the interaction logs.
    """
    # Inject interaction tracking scripts
    await origin_page.evaluate(ORIGIN_RECORDER_JS)
    await dest_page.evaluate(DEST_RECORDER_JS)

    print("\n" + "=" * 70)
    print("  OBSERVATION PHASE")
    print("=" * 70)
    print("""
  Two browser tabs are open:
    • Tab 1 (Origin): saucedemo.com – log in and navigate to a product/cart.
    • Tab 2 (Destination): Order Ingestion Portal – our internal ERP form.

  YOUR TASK:
    1. Log into saucedemo.com (user: standard_user / pass: secret_sauce)
    2. Add an item to the cart and go to checkout.
    3. Copy data from Tab 1 and paste/type it into the form fields in Tab 2.
    4. When done, come back here and press ENTER.
""")
    print("=" * 70)

    # Block until user signals completion
    await asyncio.get_event_loop().run_in_executor(
        None, lambda: input("\n⏳ Press ENTER when you've finished demonstrating...\n")
    )

    # Collect interaction logs from both tabs
    origin_log = await origin_page.evaluate("window.__recorder_log || []")
    dest_log = await dest_page.evaluate("window.__recorder_log || []")

    # Also capture the destination form structure for context
    dest_fields = await dest_page.evaluate("""
        Array.from(document.querySelectorAll('input, textarea')).map(el => ({
            id: el.id,
            name: el.name,
            label: el.closest('.form-group')?.querySelector('label')?.innerText || '',
            type: el.type,
            tag: el.tagName.toLowerCase()
        }))
    """)

    print(f"\n📊 Captured {len(origin_log)} origin events, {len(dest_log)} destination events.")

    # ─── Ask LLM to infer mappings ───────────────────────────────────────────────
    system_prompt = """You are an expert data-mapping analyst. You observe user interactions 
between two web systems and deduce the semantic field mapping. You MUST output ONLY valid JSON, 
no markdown, no explanation."""

    user_prompt = f"""I observed a user copying data from a source web application (an e-commerce site) 
and pasting/typing it into a destination form (an internal ERP).

Here is the interaction log from the SOURCE system (what the user clicked/copied):
{json.dumps(origin_log, indent=2)}

Here is the interaction log from the DESTINATION system (where the user pasted/typed data):
{json.dumps(dest_log, indent=2)}

Here is the structure of the destination form:
{json.dumps(dest_fields, indent=2)}

Based on these observations, produce a JSON mapping object. Each key should be a semantic 
description of the data from the origin (e.g., "product_name", "price", "first_name"), 
and each value should be an object with:
- "destination_selector": the CSS selector to target the field (use #id)
- "description": a brief note on what this field represents

Output ONLY the JSON object. Example format:
{{
    "product_name": {{
        "destination_selector": "#item_title",
        "description": "The name/title of the product"
    }}
}}
"""

    print("\n🤖 Asking LLM to infer field mapping...")
    raw_response = await call_llm(system_prompt, user_prompt)

    # Parse the mapping
    try:
        # Handle potential markdown code fences in response
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            cleaned = cleaned.rsplit("```", 1)[0]
        mapping = json.loads(cleaned)
    except json.JSONDecodeError:
        print(f"⚠️  LLM returned non-JSON. Raw response:\n{raw_response}")
        mapping = {}

    print("\n✅ Inferred Mapping:")
    print(json.dumps(mapping, indent=2))
    return mapping


# ─── Phase 3: Automation ──────────────────────────────────────────────────────────
async def automate(origin_page: Page, dest_page: Page, mapping: dict):
    """
    Scrape the current state of the origin page, ask the LLM to format
    a fill payload using the learned mapping, then fill the destination form.
    """
    print("\n" + "=" * 70)
    print("  AUTOMATION PHASE")
    print("=" * 70)
    print("""
  Now navigate to a NEW product or cart page in Tab 1 (Origin).
  The AI will scrape the page and fill the destination form automatically.
""")
    print("=" * 70)

    await asyncio.get_event_loop().run_in_executor(
        None, lambda: input("\n⏳ Press ENTER when you're on the new page to automate...\n")
    )

    # Scrape visible text and structured data from Origin
    page_data = await origin_page.evaluate("""
    (() => {
        const data = {};

        // Grab all visible text blocks
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

        // Grab input field values (checkout forms)
        document.querySelectorAll('input').forEach(el => {
            if (el.value) {
                data[el.id || el.name || el.placeholder] = el.value;
            }
        });

        // Get all visible text as fallback context
        data['_page_text'] = document.body.innerText.substring(0, 3000);

        return data;
    })()
    """)

    print(f"\n📄 Scraped {len(page_data)} data points from origin page.")

    # ─── Ask LLM to produce fill instructions ────────────────────────────────────
    system_prompt = """You are a data-transformation agent. Given raw scraped data from a source 
web page and a field mapping schema, produce exact values to fill into the destination form.
Output ONLY valid JSON, no markdown, no explanation."""

    user_prompt = f"""Here is raw data scraped from the source e-commerce page:
{json.dumps(page_data, indent=2)}

Here is the learned field mapping (semantic_key -> destination_selector):
{json.dumps(mapping, indent=2)}

Produce a JSON object where each key is the destination CSS selector (e.g., "#item_title") 
and the value is the exact string to type into that field. Extract the appropriate data from 
the scraped source to fill each destination field.

If a field cannot be filled from the available data, omit it.

Output ONLY the JSON object. Example:
{{
    "#item_title": "Sauce Labs Backpack",
    "#unit_cost": "29.99"
}}
"""

    print("\n🤖 Asking LLM to format fill payload...")
    raw_response = await call_llm(system_prompt, user_prompt)

    try:
        cleaned = raw_response.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            cleaned = cleaned.rsplit("```", 1)[0]
        fill_payload = json.loads(cleaned)
    except json.JSONDecodeError:
        print(f"⚠️  LLM returned non-JSON. Raw response:\n{raw_response}")
        return

    print("\n📝 Fill Payload:")
    print(json.dumps(fill_payload, indent=2))

    # ─── Fill the destination form ────────────────────────────────────────────────
    print("\n🚀 Filling destination form...")
    for selector, value in fill_payload.items():
        try:
            await dest_page.fill(selector, str(value))
            print(f"   ✓ {selector} = {value}")
        except Exception as e:
            print(f"   ✗ {selector} failed: {e}")

    print("\n✅ Automation complete! The destination form has been filled.")

    # Optionally submit
    await asyncio.get_event_loop().run_in_executor(
        None, lambda: input("\n⏳ Press ENTER to submit the form (or Ctrl+C to skip)...\n")
    )
    try:
        await dest_page.click("button[type='submit']")
        print("📨 Form submitted!")
    except Exception:
        print("ℹ️  No submit button found or submission skipped.")


# ─── Main Entry Point ─────────────────────────────────────────────────────────────
async def main():
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║        🤖 Autonomous Web Data Replicator – Hackathon PoC           ║
╠══════════════════════════════════════════════════════════════════════╣
║  This agent learns data-entry patterns by watching you, then       ║
║  replicates the process autonomously using LLM-inferred mappings.  ║
╚══════════════════════════════════════════════════════════════════════╝
    """)

    dest_url = f"file://{DEST_FILE.resolve()}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()

        # Phase 1: Open two tabs
        origin_page = await context.new_page()
        dest_page = await context.new_page()

        print("🌐 Opening Origin (saucedemo.com)...")
        await origin_page.goto(ORIGIN_URL, wait_until="domcontentloaded")

        print("🌐 Opening Destination (Order Ingestion Portal)...")
        await dest_page.goto(dest_url, wait_until="domcontentloaded")

        # Phase 2: Observation
        mapping = await observe(origin_page, dest_page)

        if not mapping:
            print("\n❌ No mapping could be inferred. Exiting.")
            await browser.close()
            return

        # Phase 3: Automation
        await automate(origin_page, dest_page, mapping)

        print("\n🏁 Session complete. Closing browser in 5 seconds...")
        await asyncio.sleep(5)
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())

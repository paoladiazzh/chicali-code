# Autonomous Web Data Replicator

An AI-powered automation tool that learns web-based data entry processes by observation and executes them autonomously, completely eliminating the need for hardcoded RPA rules or traditional EDI setups.

## 🚀 The Challenge
Moving data between modern web portals (e.g., retail purchase orders) and internal systems is highly manual. Traditional EDI integrations take months per portal. This solution bridges the gap using an LLM-backed Playwright agent that watches a user perform the task once, deduces the data mapping, and takes over — working with **any** origin website.

## 🛠 Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend / Orchestrator** | Python 3.12, FastAPI, Uvicorn |
| **Browser Automation** | Playwright (Async API) |
| **AI / LLM** | Google Gemini 2.5 Flash (OpenAI-compatible endpoint) |
| **Frontend / Dashboard** | HTML5, TailwindCSS (CDN), Chart.js 4, WebSockets |
| **Templating** | Jinja2 |
| **Config** | python-dotenv |

## 📂 Project Structure

```
chicali-code/
├── app.py                    # FastAPI orchestrator (dashboard + API endpoints)
├── llm_engine.py             # Gemini API module with token tracking & cost metrics
├── main.py                   # Standalone CLI orchestrator (original PoC)
├── destination_mock.html     # Mock ERP form (System B)
├── requirements.txt          # Python dependencies
├── .env.example              # Environment variable template
├── .gitignore
├── templates/
│   └── dashboard.html        # Dashboard UI (KPIs, charts, records table, logs)
└── static/
    └── app.js                # Frontend logic (WebSocket, Chart.js, table rendering)
```

## ⚙️ How It Works

### Phase 1: Connection
- Launches a Playwright browser with two tabs.
- **Tab 1 (Origin):** Any user-specified URL (configurable from the dashboard).
- **Tab 2 (Destination):** Local ERP form with intentionally different field naming.
- Injects JavaScript event recorders into both tabs.

### Phase 2: Observation
- User demonstrates the data-entry process manually (copy from Tab 1 → paste into Tab 2).
- JavaScript captures all `copy`, `click`, `input`, and `paste` events with timestamps.
- Interaction logs + destination form schema are sent to Gemini.
- LLM infers a semantic field mapping dynamically (**no hardcoded mappings**).

### Phase 3: Automation
- User navigates to a new page in Tab 1 (new product, new order, etc.).
- A generic DOM scraper extracts all visible text, inputs, tables, and data attributes.
- LLM transforms the scraped data using the learned mapping into a fill payload.
- Playwright autonomously fills the destination form.

## 📊 Dashboard Features

Access at `http://localhost:8000` after starting the server.

- **Dynamic Origin URL** — paste any website URL, no code changes needed.
- **KPI Row** — Total Tokens Consumed, Estimated Cost ($), Successful Mappings.
- **Token Usage Chart** — Line chart showing input/output tokens per LLM call.
- **Mapping Accuracy Chart** — Doughnut chart of successful vs. failed fills.
- **Records Table** — Spreadsheet-style log of all mapped fields and filled values.
- **Live Agent Logs** — Real-time scrolling terminal via WebSocket.

## ⚙️ Setup Instructions

1. **Clone and create a virtual environment:**
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

3. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your Gemini API key
   ```

4. **Run the dashboard:**
   ```bash
   python app.py
   ```
   Open `http://localhost:8000` in your browser.

5. **Or run the standalone CLI version:**
   ```bash
   python main.py
   ```

## 🔑 Environment Variables

| Variable | Description |
|----------|-------------|
| `GEMINI_API_KEY` | Your Google Gemini API key |
| `GEMINI_MODEL` | Model name (default: `gemini-2.5-flash`) |

## 🌐 Supported Origin Sites

The agent works with **any** website. Tested with:

| Website | Use Case |
|---------|----------|
| https://saucedemo.com | E-commerce demo (login, cart, checkout) |
| https://automationexercise.com | Registration, product search, forms |



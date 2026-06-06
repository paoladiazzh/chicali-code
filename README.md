# Autonomous Web Data Replicator

An AI-powered automation tool that learns web-based data entry processes by observation and executes them autonomously, completely eliminating the need for hardcoded RPA rules or traditional EDI setups.

## 🚀 The Challenge
Moving data between modern web portals (e.g., retail purchase orders) and internal systems is highly manual. Traditional EDI integrations take months. This solution bridges the gap using an LLM-backed Playwright agent that watches a user perform the task once, deduces the data mapping, and takes over.

## 🛠 Tech Stack
* **Language:** Python 3.x
* **Browser Automation:** Playwright (Async API)
* **Intelligence:** Azure OpenAI / GPT-4o
* **Environment:** `python-dotenv`

## 📂 Project Structure
* `main.py`: Core orchestrator containing the Observation and Automation phases.
* `destination_mock.html`: Mock internal ERP system (System B) with intentionally different field naming.
* `requirements.txt`: Python dependencies.
* `.env.example`: Template for environment variables.
* `.env`: Your local environment variables (API keys – not committed).

## ⚙️ How It Works

### Phase 1 & 2: Connection & Observation
1. Launches a Playwright browser with two tabs (Origin: saucedemo.com, Destination: local ERP form).
2. Injects JavaScript recorders to capture user copy/paste/type interactions.
3. User demonstrates the data-entry process manually.
4. Interaction logs are sent to GPT-4o which infers a semantic field mapping (no hardcoding!).

### Phase 3: Automation
1. User navigates to a new product/cart page.
2. Agent scrapes the origin page's current state.
3. LLM transforms scraped data using the learned mapping into a fill payload.
4. Playwright fills the destination form autonomously.

## ⚙️ Setup Instructions

1. **Clone and create a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows use: venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   playwright install chromium
   ```

3. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env with your Azure OpenAI credentials
   ```

4. **Run:**
   ```bash
   python main.py
   ```

## 🔑 Environment Variables

| Variable | Description |
|----------|-------------|
| `AZURE_OPENAI_ENDPOINT` | Your Azure OpenAI resource endpoint |
| `AZURE_OPENAI_API_KEY` | API key for the deployment |
| `AZURE_OPENAI_DEPLOYMENT` | Model deployment name (e.g., `gpt-4o`) |
| `AZURE_OPENAI_API_VERSION` | API version (default: `2024-02-15-preview`) |

## 🎯 Demo Credentials (saucedemo.com)
- **Username:** `standard_user`
- **Password:** `secret_sauce`
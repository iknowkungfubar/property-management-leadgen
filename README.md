# Property Management LeadGen

Automated lead generation for small property management firms.  
Targets **Orange County, CA** and surrounding areas (Los Angeles County).

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Tauri v2 (Rust)                    │
│  ┌───────────┐   IPC (stdin/stdout JSON)           │
│  │  WebView  │◄──────────────────────────► Python  │
│  │  (Vite +  │      sidecar (src/main.py)          │
│  │  Tailwind │                                     │
│  │  Alpine)  │    ┌─────────────────┐              │
│  └───────────┘    │ Agents:         │              │
│  Frontend         │  Discovery      │              │
│  (port 1420)      │  EntityUnmask   │              │
│                   │  MarketIntell   │              │
│                   │  OutputSynth    │              │
│                   │                 │              │
│                   │ Scrapers:       │              │
│                   │  CA SOS Parser  │              │
│                   │  County ArcGIS  │              │
│                   │  Rental List    │              │
│                   │                 │              │
│                   │ DB: SQLite WAL  │              │
│                   │ LLM: Poly-prov  │              │
│                   └─────────────────┘              │
└─────────────────────────────────────────────────────┘
```

### Core Agents

| Agent | Responsibility |
|-------|---------------|
| **Discovery Agent** | CSV import (Orange Coast Title, CRMLS), address normalisation, APN lookup via county assessor ArcGIS endpoints, absentee-owner flagging |
| **Entity Unmasking Agent** | CA Secretary of State entity search (bizfileOnline), Statement of Information PDF parsing via LLM, principal extraction |
| **Market Intelligence Agent** | FRBO/Craigslist vacancy detection, code enforcement portal scraping, lead priority scoring (L_score formula) |
| **Output Synthesis Agent** | DNC compliance filtering, deduplication, CRM export (CSV / JSON / HubSpot format) |

### Lead Priority Score

```text
L_score = α · R_vac + β · (M_target - M_current) − γ · S_comp
```

Where α=0.4, β=0.4, γ=0.2 by default.

### LLM Layer

The LLM provider is **polymorphic** — choose your backend in Settings:

| Provider | Backend |
|----------|---------|
| **Anthropic** | `claude-sonnet-4-20250514` via Messages API |
| **OpenAI** | `gpt-4o` via /chat/completions |
| **OpenPipe** | Fine-tuned models via OpenAI-compatible API |
| **Local Ollama** | Local models via /chat/completions |

All providers enforce structured JSON output through a common `LLMProvider` abstract base.

---

## Development Setup

### Prerequisites

- **Python** 3.11+
- **Node.js** 20+
- **Rust** 1.77+ (for Tauri)
- **cargo install tauri-cli**

### Quick Start

```bash
# 1. Python dependencies
pip install -r requirements.txt

# 2. Node dependencies
cd frontend && npm install && cd ..

# 3. Install Playwright browsers
python -m playwright install chromium

# 4. Run in dev mode
cargo tauri dev
```

### Run tests

```bash
pytest tests/ -v
```

### Lint

```bash
ruff check src/
```

### Manual sidecar test (without Tauri)

```bash
echo '{"method":"ping","params":{}}' | uv run python src/main.py
```

---

## Project Structure

```
property-management-leadgen/
├── src-tauri/           # Tauri Rust shell
│   ├── Cargo.toml
│   ├── tauri.conf.json
│   └── src/main.rs
├── src/                  # Python sidecar package
│   ├── main.py           # Entrypoint — stdin JSON loop
│   ├── agents/           # 4 core pipeline agents
│   ├── db/               # SQLite schema, migrations, connection
│   ├── llm/              # LLM provider abstraction
│   ├── scrapers/         # Web scrapers (CA SoS, assessor, rentals)
│   ├── captcha/          # CAPTCHA detection & modal handling
│   ├── compliance/       # DNC compliance
│   └── utils/            # Rate limiter, CSV import utilities
├── frontend/             # Tauri webview UI
│   ├── index.html
│   ├── package.json
│   └── src/
│       ├── app.js        # Alpine.js app entry
│       ├── components/   # Dashboard, LeadTable, Settings, CaptchaModal
│       └── styles/       # Tailwind CSS
├── tests/                # pytest suite
├── pyproject.toml
├── requirements.txt
└── README.md
```

## Engineering Standards

See [CLAUDE.md](CLAUDE.md) for full details.

- Type hints on all Python function signatures
- pydantic models for data structures (planned)
- 80%+ test coverage
- Ruff linting (line-length=100)
- Exponential backoff with jitter for all scrapers
- Graceful degradation — if one agent fails, log and continue
- Sidecar zombie prevention — parent PID watchdog
- CAPTCHA state recovery without credential exposure
- DNC registry check before any lead export

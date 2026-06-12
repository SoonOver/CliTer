<div align="center">
  <h1>🖥️ CliTer</h1>
  <p><strong>Command Line Interface Termux</strong> — AI Agent dengan TUI untuk Terminal</p>
  <p>
    <img src="https://img.shields.io/badge/Python-3.11+-blue?logo=python&logoColor=white" alt="Python">
    <img src="https://img.shields.io/badge/License-MIT-green" alt="License">
    <img src="https://img.shields.io/badge/TUI-Textual-8A2BE2" alt="TUI">
    <img src="https://img.shields.io/badge/Status-Active-brightgreen" alt="Status">
    <img src="https://img.shields.io/badge/Termux-Ready-orange?logo=gnubash&logoColor=white" alt="Termux">
  </p>
  <br>
</div>

---

**CliTer** adalah AI agent canggih yang berjalan langsung di terminal/termux. Dilengkapi **Textual TUI**, **multi-provider LLM proxy**, **tool calling**, **self-improvement**, dan **autonomous planner** — semua tanpa GUI.

> 🔥 Dibuat untuk: OSINT, bug bounty, exploit research, dan workflow automation di terminal.

---

## ✨ Fitur Unggulan

### 🖥️ Terminal UI (Textual)
| Tombol | Fungsi |
|--------|--------|
| `Ctrl+D` | Dashboard — overview sistem |
| `Ctrl+P` | Provider Manager — atur LLM provider |
| `Ctrl+T` | Strategy Settings — routing + budget |
| `Ctrl+N` | New Session |
| `Ctrl+Q` | Quit |

### 🌐 Multi-Provider Proxy
Auto-routing request LLM ke berbagai provider. Dapat **failover** saat rate-limit, **round-robin**, **cheapest** routing, plus health monitor otomatis.

```
OpenRouter ──┐
Cloudflare ──┤
Nvidia    ──┤──► [Proxy:20129] ──► CliTer Agent
Local     ──┤
Xai       ──┘
```

### 🛠️ Tool Calling (9 tools)
Agent bisa pakai tools ini langsung dari chat:
```
🔧 terminal      → execute shell commands
📄 read_file     → baca file dengan offset
✏️ write_file    → tulis/overwrite file
🔍 search_files  → grep/find files
🩹 patch_file    → fuzzy find-and-replace
🌐 web_search    → DuckDuckGo, no API key
📡 fetch_url     → scrape clean text dari web
🐍 execute_python → sandboxed python runner
🧠 self_improve  → agent nambah skill sendiri!
```

### 🤖 Autonomous Planner
Multi-step task execution otomatis tanpa campur tangan tiap langkah.

```
> /plan Cari data NIK 3273051203940001 dari semua sumber

🧠 Planning...
  → Web search NIK (web_search)
  → Scrape hasil pencarian (fetch_url)
  → Simpan hasil (write_file)
  → Generate report (execute_python)
✅ Done — 4 langkah, 12.3 detik
```

### 🧠 Self-Improvement System
Agent bisa nulis skill baru + nambah tools sendiri lewat chat. Skill otomatis di-load ke system prompt di turn berikutnya.

### 💾 Export/Import
Backup semua state (provider, config, skill, session, memory) ke JSON. Bisa dipindah antar instance Termux.

---

## 🚀 Quick Start

### Installation
```bash
# Clone
git clone https://github.com/SoonOver/CliTer.git
cd CliTer

# Install dependencies
pip install -r requirements.txt

# Run
python -m cliter
```

### Konfigurasi Provider Pertama
```bash
# Di dalam TUI, tekan Ctrl+P → Add
Name:      OpenRouter
Prefix:    or
Base URL:  https://openrouter.ai/api/v1
API Key:   sk-or-...
Models:    anthropic/claude-sonnet-4, openai/gpt-4o
Priority:  10
```

Atau import dari 9Router:
```
/proxy import9r
```

---

## 📋 Semua Commands

| Command | Fungsi |
|---------|--------|
| `/plan <goal>` | Eksekusi multi-step otomatis |
| `/dashboard` | Buka Dashboard (Ctrl+D) |
| `/providers` | Buka Provider Manager (Ctrl+P) |
| `/strategy` | Buka Strategy Settings (Ctrl+T) |
| `/export` | Backup semua state |
| `/export list` | Lihat daftar backup |
| `/import <path>` | Restore dari backup file |
| `/compact` | Ringkas percakapan panjang |
| `/proxy on/off/status` | Control proxy server |
| `/proxy list` | Lihat provider terdaftar |
| `/proxy add <name> <prefix> <url>` | Tambah provider |
| `/proxy addkey <name> <key>` | Set API key |
| `/model <name>` | Ganti model |
| `/strategy <mode>` | Set routing (auto/manual/fallback) |
| `/memory add/list/delete` | Manajemen memori |
| `/skills` | Lihat skill terinstall |
| `/clear` | Bersihkan chat |
| `/status` | Status sistem |

---

## 🏗️ Arsitektur

```
cliter/
├── app.py              # Main TUI application
├── core/
│   ├── agent.py        # Agent loop + tool dispatch
│   ├── planner.py      # Autonomous multi-step executor
│   ├── compactor.py    # Context summarization
│   ├── exporter.py     # Backup/restore system
│   ├── memory.py       # Persistent memory
│   └── session.py      # Conversation manager
├── proxy/
│   ├── manager.py      # Provider CRUD
│   ├── pool.py         # Connection pool + failover
│   ├── strategy.py     # Model selection strategy
│   ├── monitor.py      # Health check monitor
│   ├── tracker.py      # Reliability + budget tracker
│   └── server.py       # Proxy HTTP server
├── tools/
│   ├── terminal.py     # Shell execution
│   ├── file_ops.py     # File read/write/search/patch
│   ├── web.py          # DuckDuckGo search
│   ├── python_eval.py  # Python executor + fetch_url
│   └── self_improve.py # Skill/plugin creation
├── ui/
│   ├── dashboard_screen.py  # System overview
│   ├── provider_screen.py   # Provider manager
│   ├── strategy_screen.py   # Strategy config
│   ├── chat_panel.py        # Chat interface
│   ├── sidebar.py           # Session/tools/skills list
│   └── modal.py             # Confirm/input dialogs
├── llm/                # LLM provider adapters
├── config/             # YAML config loader
├── skills/             # Skill management
└── plugins/            # Plugin system
```

---

## 🔧 Tech Stack

- **Python 3.11+** — core runtime
- **Textual 8.x** — TUI framework
- **httpx** — async HTTP client
- **aiosqlite** — async SQLite
- **BeautifulSoup4** — web scraping
- **DuckDuckGo Search** — web search (no API key)

---

## 📸 Tampilan

```
┌─ CliTer Dashboard ─────────────────────────────────┐
│ [Strategy: auto] [Proxy: Off] [5 active providers]  │
│ ──────────────────────────────────────────────────  │
│ Providers     │ Reliability                         │
│ 🟢 Coding 100 │ prod-a1  100%  266ms  42 req        │
│ 🟢 Nvidia  90 │ prod-b2  95%   120ms  128 req       │
│ 🔴 Xai      5 │ prod-c3  88%   890ms  15 req        │
│ ──────────────────────────────────────────────────  │
│ [📊 Providers] [⚙️ Strategy] [🔄 Refresh] [✖ Close] │
└──────────────────────────────────────────────────────┘
```

---

## 👨‍💻 Author

**SoonOver** — Indonesian security researcher. OSINT, bug bounty, exploit research.

---

<p align="center">
  <b>CliTer</b> — AI Agent untuk Terminal Indonesia.<br>
  Made with ❤️ in 🇮🇩
</p>

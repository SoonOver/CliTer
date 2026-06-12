# CliTer — Command Line Interface Termux

AI agent dengan TUI untuk Termux/terminal. Multi-provider proxy, tool calling, self-improvement.

## Fitur

- **TUI** — Textual-based full TUI (Dashboard, Provider Manager, Strategy Settings)
- **Multi-Provider Proxy** — Route LLM requests across banyak API key (OpenRouter, Cloudflare, Nvidia, dll)
- **Auto Failover** — Rate-limit handling, fallback, round-robin, cheapest routing
- **Tool Calling** — web_search, read/write/patch file, terminal, python execution, fetch_url
- **Self-Improvement** — Agent bisa nambah skill sendiri via `self_improve` tool
- **Autonomous Planner** — Multi-step task execution (`/plan`)
- **Export/Import** — Backup providers, config, skills, sessions (`/export`, `/import`)
- **Context Compaction** — Smart summarization buat hemat token (`/compact`)
- **9Router Compatible** — Import provider config dari 9Router database

## Quick Start

```bash
# Install
pip install -r requirements.txt

# Run
python -m cliter

# Keybindings inside TUI:
# Ctrl+D  → Dashboard
# Ctrl+P  → Provider Manager
# Ctrl+T  → Strategy Settings
# Ctrl+N  → New Session
```

## Commands

| Command | Fungsi |
|---------|--------|
| `/plan <goal>` | Autonomous multi-step execution |
| `/dashboard` | System dashboard (Ctrl+D) |
| `/providers` | Provider Manager (Ctrl+P) |
| `/strategy` | Strategy Settings (Ctrl+T) |
| `/export` | Backup semua state |
| `/import <path>` | Restore dari backup |
| `/compact` | Compact conversation history |
| `/proxy on/off/status` | Proxy server control |

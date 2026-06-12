# CliTer — Command Line Interface Termux
# Master Implementation Plan

> **Target:** TUI-based AI agent framework mirip Hermes, optimized for Termux (Android).
> **Stack:** Python 3.11+ / Textual (TUI) / modular plugin arch
> **Branding:** CliTer

---

## Vision

CliTer = lightweight Hermes-like agent yang jalan di Termux.
TUI-based (bukan CLI biasa), punya panel chat, tool sidebar, status bar.
Modular: skill system, memory, tool routing, multi-provider LLM.

---

## Architecture Overview

```
cliter/
├── __main__.py              # entrypoint: python -m cliter
├── app.py                   # Textual App (main TUI)
├── config/
│   ├── __init__.py
│   ├── settings.py          # YAML config loader
│   └── defaults.yaml        # default config
├── core/
│   ├── __init__.py
│   ├── agent.py             # main agent loop (prompt → LLM → tool → response)
│   ├── memory.py            # persistent memory (SQLite)
│   ├── session.py           # session/conversation manager
│   ├── router.py            # tool router (match intent → tool)
│   └── history.py           # chat history (SQLite)
├── llm/
│   ├── __init__.py
│   ├── base.py              # BaseLLMProvider ABC
│   ├── openai_compat.py     # OpenAI-compatible (OpenRouter, local, etc)
│   ├── anthropic.py         # Anthropic Claude
│   └── google.py            # Gemini
├── tools/
│   ├── __init__.py
│   ├── base.py              # BaseTool ABC
│   ├── terminal.py          # shell exec (subprocess)
│   ├── file_ops.py          # read/write/search files
│   ├── web.py               # web search (duckduckgo, etc)
│   ├── browser.py           # lightweight headless fetch
│   └── registry.py          # tool discovery + registration
├── skills/
│   ├── __init__.py
│   ├── loader.py            # skill YAML/MD loader
│   ├── manager.py           # CRUD skills
│   └── builtin/             # bundled skills
│       └── ...
├── ui/
│   ├── __init__.py
│   ├── chat_panel.py        # main chat area (scrollable)
│   ├── input_box.py         # user input with history
│   ├── sidebar.py           # tools/skills/sessions panel
│   ├── status_bar.py        # model, tokens, session info
│   ├── modal.py             # popup dialogs (confirm, pick, etc)
│   └── theme.py             # color schemes (dark/hacker/minimal)
├── plugins/
│   ├── __init__.py
│   └── loader.py            # external plugin discovery
└── utils/
    ├── __init__.py
    ├── paths.py              # XDG / Termux path resolution
    ├── log.py                # structured logging
    └── clipboard.py          # termux-clipboard integration
```

Config dir: `~/.cliter/` (skills, memory.db, config.yaml, sessions/)

---

## Phase 1: Foundation (Core + Minimal TUI)

### Task 1.1: Project scaffold
- pyproject.toml (name=cliter, deps: textual, httpx, pyyaml, rich)
- __main__.py entrypoint
- Empty package structure semua folder di atas

### Task 1.2: Config system
- defaults.yaml — model, provider, api_key placeholder, theme
- settings.py — load YAML, merge env vars, dot-access
- Path resolution: ~/.cliter/ on Termux, fallback XDG

### Task 1.3: LLM provider abstraction
- BaseLLMProvider ABC: `async chat(messages, tools) -> response`
- OpenAI-compatible provider (covers OpenRouter, local ollama, LM Studio)
- Streaming support (yield chunks)
- Tool call parsing (OpenAI function calling format)

### Task 1.4: Basic TUI shell
- Textual App with 3 regions:
  - Header (CliTer branding + model name)
  - Chat area (scrollable, markdown-rendered messages)
  - Input box (multiline, Ctrl+Enter send)
- Status bar: token count, model, session name
- Minimal keybinds: Ctrl+Q quit, Ctrl+N new session

### Task 1.5: Agent loop
- agent.py: receive user msg → build prompt → call LLM → parse response
- Handle streaming (token-by-token to chat panel)
- Tool call detection + execution + feed result back
- System prompt with context injection

---

## Phase 2: Tools + File System

### Task 2.1: Tool base + registry
- BaseTool ABC: name, description, parameters (JSON schema), execute()
- Registry: auto-discover tools from tools/ dir
- Tool → LLM function schema conversion

### Task 2.2: Terminal tool
- subprocess exec with timeout
- Background process support (track PID)
- Working dir awareness
- Output capture + truncation for large output

### Task 2.3: File operations tool
- read_file (with line numbers, offset/limit)
- write_file (full overwrite)
- patch (find-replace)
- search_files (ripgrep wrapper or Python fallback)

### Task 2.4: Web tool
- DuckDuckGo search (no API key needed)
- URL fetch + content extraction (trafilatura or readability)
- Lightweight — no browser needed

---

## Phase 3: Memory + Sessions

### Task 3.1: SQLite memory
- memory.db in ~/.cliter/
- Tables: memories (key, value, category, timestamp)
- CRUD operations
- Auto-inject into system prompt

### Task 3.2: Session management
- Session = conversation thread (messages + metadata)
- SQLite storage
- Session list in sidebar
- Switch sessions, rename, delete
- Auto-save on each message

### Task 3.3: Chat history search
- FTS5 full-text search across sessions
- Session search command (/search query)

---

## Phase 4: Skills System

### Task 4.1: Skill format
- YAML frontmatter + markdown body (same as Hermes)
- Skill dir: ~/.cliter/skills/
- Bundled skills in package

### Task 4.2: Skill loader + manager
- Load skill by name
- List available skills
- Auto-match skills to user query (keyword trigger)
- Inject skill content into prompt

### Task 4.3: Skill CRUD
- /skill create, /skill edit, /skill delete
- Skills stored as .md files

---

## Phase 5: TUI Polish

### Task 5.1: Sidebar
- Tabs: Sessions | Tools | Skills
- Collapsible (toggle with Ctrl+B)
- Clickable items

### Task 5.2: Slash commands
- /model — switch model
- /session — session management
- /skill — skill ops
- /memory — memory ops
- /config — edit config
- /help — command list
- /clear — clear chat

### Task 5.3: Themes
- Dark (default), Hacker (green-on-black), Minimal
- Config-driven
- Syntax highlighting in code blocks

### Task 5.4: Termux integration
- termux-clipboard-get/set
- termux-notification for long tasks
- termux-vibrate on completion
- termux-open for URLs
- Detect Termux vs regular Linux

---

## Phase 6: Advanced Features

### Task 6.1: Multi-provider support
- Anthropic provider
- Google Gemini provider
- Provider switching at runtime (/model command)

### Task 6.2: Plugin system
- External plugins in ~/.cliter/plugins/
- Plugin = Python package with register() hook
- Custom tools, custom UI widgets, custom commands

### Task 6.3: Cron / scheduled tasks
- Simple job scheduler (cron syntax)
- Jobs stored in SQLite
- Background execution

### Task 6.4: MCP client (optional)
- Connect to MCP servers (stdio transport)
- Register MCP tools as native tools
- Config-driven server list

---

## Phase 7: Packaging + Distribution

### Task 7.1: pip installable
- pyproject.toml complete
- `pip install cliter` or `pip install .`
- Entry point: `cliter` command

### Task 7.2: Termux install script
- One-liner: `curl ... | bash`
- Install deps (python, pip)
- Setup ~/.cliter/
- First-run wizard (API key, model selection)

### Task 7.3: README + docs
- README.md with screenshots (textual screenshots)
- Quick start guide
- Config reference
- Tool/skill authoring guide

---

## Key Design Decisions

1. **Textual for TUI** — rich widgets, mouse support, works in Termux
2. **SQLite for everything** — memory, sessions, history. Single file, no server
3. **OpenAI-compatible first** — covers 90% use cases (OpenRouter, Ollama, etc)
4. **Async throughout** — httpx async, Textual async, non-blocking
5. **Hermes-compatible skills** — same YAML+MD format, can import Hermes skills
6. **Termux-first, Linux-second** — test on Termux, also works on any Linux
7. **Minimal deps** — textual, httpx, pyyaml, rich. No heavy frameworks

---

## Deps (minimal)

```
textual>=0.80.0       # TUI framework
httpx>=0.27.0         # async HTTP (LLM calls)
pyyaml>=6.0           # config
rich>=13.0            # markdown/syntax in TUI
aiosqlite>=0.20.0     # async SQLite
```

Optional:
```
trafilatura           # web content extraction
anthropic             # Anthropic SDK
google-genai          # Gemini SDK
```

---

## Priority Order

Phase 1 → 2 → 3 → 4 → 5 → 6 → 7

Phase 1-2 = MVP (chat + tools, usable)
Phase 3-4 = feature parity basics
Phase 5-7 = polish + distribution

Estimated: Phase 1-2 bisa jadi dalam ~2-3 hari kerja intensif.
Full Phase 1-7 = ~2-3 minggu.

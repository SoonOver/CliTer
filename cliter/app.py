"""CliTer — Main TUI Application with built-in proxy."""
import uuid
import asyncio
import json
import yaml
from pathlib import Path
from textual.app import App, ComposeResult
from textual.widgets import Header, Footer
from textual.containers import Horizontal, Vertical
from textual.binding import Binding
from textual import work

from cliter.config import settings
from cliter.core import memory, session
from cliter.core.agent import Agent
from cliter.core.planner import Planner
from cliter.core.compactor import ContextCompactor
from cliter.core.exporter import Exporter
from cliter.services.geotracker import GeoService, get_service as get_geo
from cliter.tools import registry
from cliter.skills.loader import list_skills
from cliter.plugins.loader import load_plugins
from cliter.ui.chat_panel import ChatPanel
from cliter.ui.input_box import InputBox
from cliter.ui.sidebar import Sidebar
from cliter.ui.status_bar import StatusBar
from cliter.ui.modal import InputModal
from cliter.ui.provider_screen import ProviderManagerScreen
from cliter.ui.dashboard_screen import DashboardScreen
from cliter.ui.strategy_screen import StrategyScreen
from cliter.proxy import manager as proxy_mgr
from cliter.proxy.server import ProxyServer
from cliter.proxy.nine_router import find_db, extract_api_keys, import_into_cliter
from cliter.proxy import tracker as proxy_tracker
from cliter.proxy import strategy as proxy_strategy
from cliter.proxy import pool as proxy_pool
from cliter.proxy import monitor as proxy_monitor


class CliTerApp(App):
    """CliTer TUI Application."""

    TITLE = "CliTer"
    SUB_TITLE = "Command Line Interface Termux"

    CSS = """
    Screen {
        background: $background;
    }
    #main-area {
        height: 1fr;
    }
    #chat-container {
        width: 1fr;
    }
    """

    BINDINGS = [
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+n", "new_session", "New Chat", show=True),
        Binding("ctrl+b", "toggle_sidebar", "Sidebar", show=True),
        Binding("ctrl+p", "open_providers", "Providers", show=True),
        Binding("ctrl+d", "open_dashboard", "Dashboard", show=True),
        Binding("ctrl+t", "open_strategy", "Strategy", show=True),
        Binding("ctrl+j", "send", "Send", show=False),
    ]

    def __init__(self):
        super().__init__()
        self.current_session_id: str = ""
        self.agent: Agent | None = None
        self._streaming_content: str = ""
        self._proxy_server: ProxyServer | None = None
        self._proxy_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-area"):
            yield Sidebar()
            with Vertical(id="chat-container"):
                yield ChatPanel()
                yield InputBox(id="input-box")
        yield StatusBar()
        yield Footer()

    # ── Lifecycle ─────────────────────────────────────

    async def on_mount(self):
        settings.load()

        # Init all DBs
        await memory.init_db()
        await session.init_db()
        await proxy_mgr.init_db()
        await proxy_tracker.init_db()

        # Load tools + plugins
        registry.load_defaults()
        load_plugins()

        # Seed default proxy providers on first run
        await self._seed_default_providers()

        # Update status bar
        sb = self.query_one(StatusBar)
        sb.set_model(settings.get("llm", "model", default="gpt-4o-mini"))

        # Auto-start proxy if configured
        if settings.get("proxy", "enabled", default=False):
            await self._proxy_start()

        # Auto-start geo tracker
        geo = get_geo()
        await geo.start(interval=120)  # check every 2 minutes

        # Refresh sidebar
        await self._refresh_sidebar()

        # Create or restore session
        sessions = await session.list_sessions(limit=1)
        if sessions:
            self.current_session_id = sessions[0]["id"]
            sb.set_session(sessions[0].get("title", "Chat"))
            msgs = await session.get_messages(self.current_session_id)
            chat = self.query_one(ChatPanel)
            for m in msgs:
                if m["role"] in ("user", "assistant"):
                    chat.add_message(m["role"], m["content"])
        else:
            await self._new_session()

        # Focus input
        self.query_one(InputBox).focus()

        # Welcome
        chat = self.query_one(ChatPanel)
        if not chat.children:
            msg = "**Welcome to CliTer!** 🖥️\n\nType a message and press `Ctrl+Enter` to send.\n\n**Slash commands:** `/help`, `/model`, `/proxy on`\n\n**Built-in proxy:** `/proxy on` starts an OpenAI-compatible API server (like 9Router) — manage multiple providers, all behind **one API key**."
            chat.add_message("assistant", msg)

    def on_unmount(self):
        if self._proxy_server:
            asyncio.create_task(self._proxy_server.stop())

    async def _seed_default_providers(self):
        """Seed default providers if none exist."""
        existing = await proxy_mgr.list_providers()
        if existing:
            return
        default_file = Path(__file__).parent / "proxy" / "default_providers.yaml"
        if not default_file.exists():
            return
        with open(default_file) as f:
            data = yaml.safe_load(f) or {}
        for p in data.get("providers", []):
            await proxy_mgr.add_provider(
                name=p["name"],
                prefix=p["prefix"],
                base_url=p["base_url"],
                api_key=p.get("api_key", ""),
                models=p.get("models", []),
            )

    # ── Proxy ─────────────────────────────────────────

    async def _proxy_start(self):
        if self._proxy_server and self._proxy_server.running:
            return
        host = settings.get("proxy", "host", default="127.0.0.1")
        port = settings.get("proxy", "port", default=20129)
        api_key = settings.get("proxy", "api_key", default="cliter-proxy-key")
        self._proxy_server = ProxyServer(host=host, port=port, api_key=api_key)
        self._proxy_task = asyncio.create_task(self._proxy_server.start())
        await asyncio.sleep(0.1)  # let server bind
        sb = self.query_one(StatusBar)
        sb.set_status(f"Proxy running on {host}:{port}")

    async def _proxy_stop(self):
        if self._proxy_server:
            await self._proxy_server.stop()
            self._proxy_server = None
        if self._proxy_task:
            self._proxy_task.cancel()
            self._proxy_task = None
        sb = self.query_one(StatusBar)
        sb.set_status("Proxy stopped")

    # ── Sidebar ───────────────────────────────────────

    async def _refresh_sidebar(self):
        sidebar = self.query_one(Sidebar)
        sessions_list = await session.list_sessions()
        await sidebar.refresh_sessions(sessions_list)
        await sidebar.refresh_tools(registry.all_tools())
        skills = list_skills()
        await sidebar.refresh_skills(skills)

    async def _new_session(self):
        sid = str(uuid.uuid4())[:8]
        await session.create_session(sid, "New Chat")
        self.current_session_id = sid
        self.agent = Agent(sid)
        sb = self.query_one(StatusBar)
        sb.set_session("New Chat")
        self.query_one(ChatPanel).clear_chat()
        await self._refresh_sidebar()

    def action_open_providers(self):
        """Open provider management screen (Ctrl+P)."""
        self.push_screen(ProviderManagerScreen())

    def action_open_dashboard(self):
        """Open system dashboard (Ctrl+D)."""
        self.push_screen(DashboardScreen())

    def action_open_strategy(self):
        """Open strategy settings screen (Ctrl+T)."""
        self.push_screen(StrategyScreen())

    def action_new_session(self):
        self.run_worker(self._new_session())

    def action_toggle_sidebar(self):
        self.query_one(Sidebar).toggle()

    # ── Input handling ────────────────────────────────

    async def on_input_box_submitted(self, event: InputBox.Submitted):
        text = event.value.strip()
        if not text:
            return
        if text.startswith("/"):
            await self._handle_command(text)
            return

        chat = self.query_one(ChatPanel)
        chat.add_message("user", text)
        sb = self.query_one(StatusBar)
        sb.set_status("Thinking...")

        if not self.agent:
            self.agent = Agent(self.current_session_id)
        self._do_chat(text)

    @work(thread=False)
    async def _do_chat(self, text: str):
        chat = self.query_one(ChatPanel)
        sb = self.query_one(StatusBar)

        self._streaming_content = ""
        streaming_started = False

        def on_token(chunk: str):
            nonlocal streaming_started
            self._streaming_content += chunk
            if not streaming_started:
                streaming_started = True
                chat.add_message("assistant", self._streaming_content)
            else:
                chat.update_last_assistant(self._streaming_content)

        def on_tool(name: str, result: str):
            chat.add_message("tool", f"**{name}**: {result}")
            sb.set_status(f"Running: {name}")

        self.agent.on_token(on_token)
        self.agent.on_tool(on_tool)

        try:
            result = await self.agent.chat(text)
            if not streaming_started and result:
                chat.add_message("assistant", result)
            sb.set_status("Ready")
        except Exception as e:
            chat.add_message("assistant", f"**Error:** {e}")
            sb.set_status("Error")

        # Auto-title
        msgs = await session.get_messages(self.current_session_id)
        if len(msgs) <= 3:
            user_msgs = [m for m in msgs if m["role"] == "user"]
            if user_msgs:
                title = user_msgs[0]["content"][:40]
                await session.rename_session(self.current_session_id, title)
                sb.set_session(title)
                await self._refresh_sidebar()

    # ── Commands ──────────────────────────────────────

    async def _handle_command(self, cmd: str):
        chat = self.query_one(ChatPanel)
        sb = self.query_one(StatusBar)
        parts = cmd.strip().split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if command == "/help":
            chat.add_message("assistant", """**CliTer Commands:**
- `/help` — Show this help
- `/model <name>` — Switch model
- `/provider <name>` — Switch provider
- `/clear` — Clear chat
- `/new` — New session
- `/sessions` — List sessions
- `/rename <title>` — Rename current session
- `/memory add|list|delete` — Memory management
- `/skills` — List skills
- `/config <key> <value>` — Set config
- `/theme <dark|hacker|minimal>` — Switch theme

**TUI Screens (keybindings):**
- `/dashboard` — System dashboard (Ctrl+D)
- `/providers` — Provider Manager (Ctrl+P)
- `/strategy` — Strategy & Budget settings (Ctrl+T)

**Autonomous & System:**
- `/plan <goal>` — Multi-step autonomous task execution
- `/compact` — Compact long conversation history
- `/export` — Export all config/providers/skills
- `/export list` — List backup files
- `/import <path>` — Import from backup JSON

**Geo Tracking:**
- `/geotrack now` — Force location check + gist update

**Strategy & Budget:**
- `/strategy <manual|auto|fallback|round_robin|cheapest>` — Set strategy mode
- `/budget <tokens>` — Set daily token budget (0=unlimited)
- `/usage` — Show today's token usage
- `/retest <name>` — Test provider connection
- `/status` — Show system status (strategy, connections, budget, proxy)

**Auto Monitor:**
- `/monitor check` — Run health check on all providers
- `/monitor sync` — Sync model lists from providers
- `/monitor status` — Show monitor status
- `/reliability` — Show provider success rates + latency

**Proxy (built-in API router, like 9Router):**
- `/proxy on` — Start proxy server
- `/proxy off` — Stop proxy server
- `/proxy status` — Show proxy status
- `/proxy list` — List configured providers
- `/proxy add <name> <prefix> <url>` — Add provider
- `/proxy addkey <name> <key>` — Set API key for provider
- `/proxy import9r` — Import providers from 9Router database
- `/proxy alias <prefix> <target>` — Set alias for model prefix
- `/proxy aliases` — List current aliases

**Keys:** `Ctrl+Enter` Send | `Ctrl+N` New | `Ctrl+B` Sidebar | `Ctrl+D` Dashboard | `Ctrl+P` Providers | `Ctrl+T` Strategy | `Ctrl+Q` Quit""")

        elif command == "/model":
            if args:
                settings.set_val("llm", "model", value=args)
                sb.set_model(args)
                self.agent = Agent(self.current_session_id)
                chat.add_message("assistant", f"Model switched to: **{args}**")
            else:
                current = settings.get("llm", "model")
                chat.add_message("assistant", f"Current model: **{current}**\nUsage: `/model gpt-4o`")

        elif command == "/provider":
            if args:
                settings.set_val("llm", "provider", value=args)
                self.agent = Agent(self.current_session_id)
                chat.add_message("assistant", f"Provider switched to: **{args}**")
            else:
                current = settings.get("llm", "provider")
                chat.add_message("assistant", f"Current provider: **{current}**\nUse `/providers` for TUI manager")

        elif command == "/providers":
            self.push_screen(ProviderManagerScreen())
            chat.add_message("system", "Opened Provider Manager (Ctrl+P)")  # invisible

        # ── Proxy commands ────────────────────────────────

        elif command == "/proxy":
            sub = args.split(maxsplit=1)[0] if args else ""
            sub_args = args[len(sub)+1:] if sub else ""

            if sub == "on":
                await self._proxy_start()
                settings.set_val("proxy", "enabled", value=True)
                self.agent = Agent(self.current_session_id)  # reconnect
                chat.add_message("assistant", "**Proxy server started.** CliTer now routes through proxy.\n\nAPI endpoint: `http://{}:{}`\nAPI key: `{}`".format(
                    settings.get("proxy", "host"), settings.get("proxy", "port"), settings.get("proxy", "api_key")))

            elif sub == "off":
                await self._proxy_stop()
                settings.set_val("proxy", "enabled", value=False)
                self.agent = Agent(self.current_session_id)
                chat.add_message("assistant", "Proxy server stopped. Using direct LLM connection.")

            elif sub == "status":
                running = self._proxy_server is not None and self._proxy_server.running
                providers = await proxy_mgr.list_providers()
                default = await proxy_mgr.get_default()
                lines = [
                    f"**Proxy Status:** {'✅ Running' if running else '❌ Stopped'}",
                    f"  Port: `{settings.get('proxy', 'port', default=20129)}`",
                    f"  API Key: `{settings.get('proxy', 'api_key', default='cliter-proxy-key')}`",
                    f"  Default provider: `{default or '(none)'}`",
                    f"  **{len(providers)}** provider(s) configured",
                ]
                if running:
                    lines.append(f"  Models endpoint: `http://localhost:{settings.get('proxy', 'port')}/v1/models`")
                chat.add_message("assistant", "\n".join(lines))

            elif sub == "list":
                providers = await proxy_mgr.list_providers()
                if not providers:
                    chat.add_message("assistant", "No providers configured. Add with `/proxy add`")
                    return
                default = await proxy_mgr.get_default()
                lines = ["**Configured Providers:**"]
                for p in providers:
                    marker = "★" if p["name"] == default else " "
                    models = json.loads(p.get("models", "[]"))
                    models_str = ", ".join(models[:5])
                    if len(models) > 5:
                        models_str += f" ... (+{len(models)-5})"
                    key_hidden = p["api_key"][:8] + "..." if p["api_key"] else "(no key)"
                    lines.append(f"  {marker} **{p['name']}** (`{p['prefix']}/`)")
                    lines.append(f"     → {p['base_url']} | key: {key_hidden}")
                    if models_str:
                        lines.append(f"     models: {models_str}")
                chat.add_message("assistant", "\n".join(lines))

            elif sub == "add":
                # /proxy add <name> <prefix> <base_url>
                add_parts = sub_args.split(maxsplit=2)
                if len(add_parts) < 3:
                    chat.add_message("assistant", "Usage: `/proxy add <name> <prefix> <base_url>`\nExample: `/proxy add OpenAI oai https://api.openai.com/v1`")
                    return
                name, prefix, base_url = add_parts
                try:
                    result = await proxy_mgr.add_provider(name=name, prefix=prefix, base_url=base_url)
                    chat.add_message("assistant", f"Provider **{name}** added with prefix `{prefix}/`.\nSet its API key: `/proxy addkey {name} <key>`")
                except Exception as e:
                    chat.add_message("assistant", f"Error: {e}")

            elif sub == "addkey":
                # /proxy addkey <name> <key>
                key_parts = sub_args.split(maxsplit=1)
                if len(key_parts) < 2:
                    chat.add_message("assistant", "Usage: `/proxy addkey <name> <api_key>`")
                    return
                pname, pkey = key_parts
                await proxy_mgr.set_api_key(pname, pkey)
                chat.add_message("assistant", f"API key set for **{pname}**")

            elif sub == "import9r":
                # Import from 9Router database
                sb.set_status("Importing 9Router providers...")
                result = await import_into_cliter()
                if not result["ok"]:
                    chat.add_message("assistant", f"**Import failed:** {result['error']}")
                    sb.set_status("Ready")
                    return

                lines = [f"**9Router Import Results** ({result['provider_count']} providers)"]
                lines.append(f"  DB: `{result['db_path']}`")

                # Show imported
                if result["imported"]:
                    lines.append(f"\\n**Imported/Updated:**")
                    for r in result["imported"]:
                        status_icon = "✅" if r["status"] == "imported" else "🔄" if r["status"] == "updated" else "❌"
                        lines.append(f"  {status_icon} {r['name']} — {r['status']}")

                # Show skipped
                if result["skipped"]:
                    lines.append(f"\\n**Skipped ({len(result['skipped'])}):**")
                    for s in result["skipped"]:
                        lines.append(f"  ⏭️ {s['name']} ({s['reason']})")

                # Show unaccounted prefixes
                if result.get("unaccounted_prefixes"):
                    lines.append(f"\\n**Unmapped combo prefixes ({len(result['unaccounted_prefixes'])}):**")
                    lines.append(f"  {', '.join(result['unaccounted_prefixes'])}")
                    lines.append("  These prefixes exist in 9Router combos but no matching provider found.")
                    lines.append("  Add with: `/proxy add <name> <prefix> <base_url>`")

                # Show 9Router's API key
                if result["proxy_keys"]:
                    lines.append(f"\\n**9Router API keys found:** {len(result['proxy_keys'])}")
                    for pk in result["proxy_keys"]:
                        lines.append(f"  🔑 {pk}")

                # Show prefix aliases
                if result.get("prefix_aliases"):
                    lines.append(f"\\n**Prefix aliases created:**")
                    for alias, target in result["prefix_aliases"].items():
                        lines.append(f"  ↪ `{alias}/` → `{target}/`")

                chat.add_message("assistant", "\\n".join(lines))
                await self._refresh_sidebar()
                sb.set_status("Ready")

            elif sub == "alias":
                # /proxy alias <from> <to>
                alias_parts = sub_args.split(maxsplit=1)
                if len(alias_parts) < 2:
                    chat.add_message("assistant", "Usage: `/proxy alias <from_prefix> <to_prefix>`\\nExample: `/proxy alias gh 1` (routes `gh/model` → provider with prefix `1`)")
                    return
                from_p, to_p = alias_parts
                existing = await proxy_mgr.get_model_aliases()
                existing[from_p] = to_p
                await proxy_mgr.set_model_aliases(existing)
                chat.add_message("assistant", f"Alias created: `{from_p}/` → `{to_p}/`")

            elif sub == "remove":
                if not sub_args:
                    chat.add_message("assistant", "Usage: `/proxy remove <name>`")
                    return
                ok = await proxy_mgr.remove_provider(sub_args)
                chat.add_message("assistant", f"Provider **{sub_args}** removed." if ok else f"Provider **{sub_args}** not found.")

            elif sub == "models":
                # /proxy models <name> <model1> <model2> ...
                model_parts = sub_args.split(maxsplit=1)
                if len(model_parts) < 2:
                    chat.add_message("assistant", "Usage: `/proxy models <name> <model1> <model2> ...`\nExample: `/proxy models OpenAI gpt-4o gpt-4o-mini`")
                    return
                pname, models_str = model_parts
                models = models_str.split()
                await proxy_mgr.set_provider_models(pname, models)
                chat.add_message("assistant", f"Models set for **{pname}**: {', '.join(models)}")

            elif sub == "default":
                if not sub_args:
                    chat.add_message("assistant", "Usage: `/proxy default <name>`\nUse `/proxy default` (no name) to clear default.")
                    return
                await proxy_mgr.set_default(sub_args)
                chat.add_message("assistant", f"Default provider set to: **{sub_args}**")

            elif sub == "":
                chat.add_message("assistant", "Usage: `/proxy <on|off|status|list|add|addkey|import9r|alias|aliases>`\nType `/help` for details.")

            else:
                chat.add_message("assistant", f"Unknown proxy subcommand: `{sub}`\nType `/help` for proxy commands.")

        # ── Other commands ─────────────────────────────

        elif command == "/clear":
            chat.clear_chat()

        elif command == "/new":
            await self._new_session()
            chat.add_message("assistant", "New session started.")

        elif command == "/sessions":
            sessions_list = await session.list_sessions()
            if sessions_list:
                lines = ["**Sessions:**"]
                for s in sessions_list:
                    marker = "→ " if s["id"] == self.current_session_id else "  "
                    lines.append(f"{marker}`{s['id']}` {s.get('title', 'Untitled')}")
                chat.add_message("assistant", "\n".join(lines))
            else:
                chat.add_message("assistant", "No sessions.")

        elif command == "/rename":
            if args:
                await session.rename_session(self.current_session_id, args)
                sb.set_session(args)
                await self._refresh_sidebar()
                chat.add_message("assistant", f"Session renamed: **{args}**")
            else:
                chat.add_message("assistant", "Usage: `/rename <title>`")

        elif command == "/memory":
            sub_parts = args.split(maxsplit=1)
            sub = sub_parts[0] if sub_parts else ""
            sub_args = sub_parts[1] if len(sub_parts) > 1 else ""

            if sub == "add" and sub_args:
                mid = await memory.add(sub_args)
                chat.add_message("assistant", f"Memory added (ID: {mid})")
            elif sub == "list":
                mems = await memory.list_all()
                if mems:
                    lines = ["**Memories:**"]
                    for m in mems:
                        lines.append(f"  [{m['id']}] ({m['category']}) {m['content']}")
                    chat.add_message("assistant", "\n".join(lines))
                else:
                    chat.add_message("assistant", "No memories saved.")
            elif sub == "delete" and sub_args:
                try:
                    await memory.remove(int(sub_args))
                    chat.add_message("assistant", f"Memory {sub_args} deleted.")
                except ValueError:
                    chat.add_message("assistant", "Usage: `/memory delete <id>`")
            else:
                chat.add_message("assistant", "Usage: `/memory add <text>` | `/memory list` | `/memory delete <id>`")

        elif command == "/skills":
            skills = list_skills()
            if skills:
                lines = ["**Skills:**"]
                for s in skills:
                    lines.append(f"  📚 {s['name']} — {s.get('description', '')}")
                chat.add_message("assistant", "\n".join(lines))
            else:
                chat.add_message("assistant", "No skills installed. Add .md files to ~/.cliter/skills/")

        elif command == "/config":
            if args:
                key_val = args.split(maxsplit=1)
                if len(key_val) == 2:
                    keys = key_val[0].split(".")
                    settings.set_val(*keys, value=key_val[1])
                    chat.add_message("assistant", f"Config set: {key_val[0]} = {key_val[1]}")
                else:
                    val = settings.get(*key_val[0].split("."))
                    chat.add_message("assistant", f"{key_val[0]} = {val}")
            else:
                chat.add_message("assistant", "Usage: `/config llm.model gpt-4o` or `/config llm.model`")

        elif command == "/theme":
            themes = ["dark", "hacker", "minimal"]
            if args in themes:
                settings.set_val("ui", "theme", value=args)
                chat.add_message("assistant", f"Theme set to: **{args}** (restart to apply)")
            else:
                chat.add_message("assistant", f"Themes: {', '.join(themes)}")

        # ── Strategy commands ────────────────────────────

        elif command == "/strategy":
            valid = ["manual", "auto", "fallback", "round_robin", "cheapest"]
            if args in valid:
                settings.set_val("strategy", "mode", value=args)
                settings.load()
                chat.add_message("assistant", f"Strategy switched to: **{args}**\n\nUse `/dashboard` or `/strategy` for TUI settings.")
            else:
                current = proxy_strategy.settings.get("strategy", "mode", default="auto")
                chat.add_message("assistant", f"Current strategy: **{current}**\n\nOptions: `manual`, `auto`, `fallback`, `round_robin`, `cheapest`")

        elif command == "/budget":
            if args:
                try:
                    tokens = int(args)
                    if tokens <= 0:
                        tokens = 0
                    await proxy_tracker.set_budget(tokens)
                    settings.set_val("strategy", "budget_daily", value=tokens)
                    chat.add_message("assistant", f"Daily budget set to: **{tokens}** tokens\n"
                        f"0 = unlimited")
                except ValueError:
                    chat.add_message("assistant", "Usage: `/budget <tokens>`\nExample: `/budget 100000` (100K tokens/day)\n`/budget 0` = unlimited")
            else:
                budget = await proxy_tracker.get_budget()
                limit_display = budget["limit"] if budget["limit"] > 0 else "unlimited"
                pct = f"({budget['used']/budget['limit']*100:.0f}%)" if budget['limit'] > 0 else ""
                chat.add_message("assistant", f"**Daily Budget:** {budget['used']} / {limit_display} tokens {pct}")

        elif command == "/usage":
            summary = await proxy_tracker.get_usage_summary(days=1)
            if not summary:
                chat.add_message("assistant", "No usage data for today yet.")
            else:
                lines = ["**Usage Today:**"]
                total_cost = 0
                for s in summary:
                    total_cost += s.get("cost", 0)
                    lines.append(f"  {s['provider_id'][:12]} | {s['model'][:20]:20s} | {s.get('requests',0)}req | {s.get('prompt',0)}p + {s.get('completion',0)}c tok")
                lines.append(f"  Total cost: ${total_cost:.4f}")
                chat.add_message("assistant", "\n".join(lines))

        elif command == "/retest":
            if args:
                sb.set_status(f"Testing {args}...")
                result = await proxy_pool.test_connection(args)
                if result.get("ok"):
                    chat.add_message("assistant", f"**{args}** ✅ — {result['models']} models available (HTTP {result['status']})")
                else:
                    chat.add_message("assistant", f"**{args}** ❌ — {result.get('error', 'unknown error')}")
                sb.set_status("Ready")
            else:
                chat.add_message("assistant", "Usage: `/retest <provider_name>`\nExample: `/retest OpenAI`")

        elif command == "/status":
            strat_info = await proxy_strategy.get_strategy_info()
            budget = await proxy_tracker.get_budget()
            mon_info = await proxy_monitor.get_monitor_status()
            lines = [
                "**CliTer Status**",
                f"  Strategy: **{strat_info['strategy']}**",
                f"  Connections: {strat_info['total_connections']} total, {strat_info['available']} available, {strat_info['rate_limited']} rate-limited",
                f"  Budget: {budget['used']} / {budget['limit'] if budget['limit'] > 0 else 'unlimited'} tokens",
                f"  Proxy: {'🟢 Running' if self._proxy_server and self._proxy_server.running else '🔴 Stopped'}",
                f"  Monitor: {'🟢 Running' if mon_info['running'] else '🔴 Stopped'}",
                f"  Providers: {mon_info['active']} active, {mon_info['inactive']} inactive",
            ]
            chat.add_message("assistant", "\n".join(lines))

        elif command == "/monitor":
            sub = args.split(maxsplit=1)[0] if args else ""
            if sub == "check":
                sb.set_status("Running health check...")
                result = await proxy_monitor.run_health_check(log_results=True)
                lines = [f"**Health Check Complete**",
                         f"  ✅ Healthy: {result['healthy']}",
                         f"  ⚠️  Degraded: {result['degraded']}",
                         f"  ❌ Dead (auto-disabled): {result['dead']}",
                         f"  🔄 Recovered (re-enabled): {result['recovered']}"]
                chat.add_message("assistant", "\n".join(lines))
                sb.set_status("Ready")
            elif sub == "sync":
                sb.set_status("Syncing models from providers...")
                count = await proxy_monitor.sync_all_models()
                chat.add_message("assistant", f"**Model Sync:** {count} provider model lists updated")
                sb.set_status("Ready")
            elif sub == "status":
                info = await proxy_monitor.get_monitor_status()
                chat.add_message("assistant", f"**Monitor Status:** {'Running' if info['running'] else 'Stopped'}\\n"
                    f"  Providers: {info['active']} active, {info['inactive']} inactive\\n"
                    f"  Rate-limited: {info['rate_limited']}\\n"
                    f"  Check interval: {info['check_interval']}s")
            else:
                chat.add_message("assistant", "**Monitor commands:**\n- `/monitor check` — Run health check on all providers\n- `/monitor sync` — Sync model lists from providers\n- `/monitor status` — Show monitor status")

        elif command == "/reliability":
            rels = await proxy_tracker.get_reliabilities()
            if not rels:
                chat.add_message("assistant", "No reliability data yet. Use some providers first.")
            else:
                lines = ["**Provider Reliability:**"]
                for r in rels:
                    pid = r.get("provider_id", "?")[:12]
                    rate = r.get("success_rate", 100.0)
                    lat = r.get("avg_latency_ms", 0)
                    total = r.get("total_requests", 0)
                    lines.append(f"  {pid:12s} | {bar} {rate:5.1f}% | avg {lat:.0f}ms | {total} req")
                chat.add_message("assistant", "\n".join(lines))

        elif command == "/dashboard":
            self.push_screen(DashboardScreen())
            chat.add_message("system", "Opened Dashboard (Ctrl+D)")

        elif command == "/strategy":
            self.push_screen(StrategyScreen())
            chat.add_message("system", "Opened Strategy Settings (Ctrl+T)")

        # ── Planner ───────────────────────────────────

        elif command == "/plan":
            if not args:
                chat.add_message("assistant", "Usage: `/plan <goal>` — Autonomous multi-step task execution.\n"
                    "Example: `/plan Cari data NIK 3273051203940001 dari semua sumber`")
            else:
                chat.add_message("assistant", f"🧠 **Planning:** {args}\nWorking on it...")
                planner = Planner()
                result = await planner.execute(args)
                chat.add_message("assistant", result)

        # ── Context compaction ────────────────────────

        elif command == "/compact":
            compactor = ContextCompactor(threshold=10)
            ok = await compactor.check_and_compact(self.current_session_id)
            if ok:
                chat.add_message("assistant", "✅ Old messages compacted. Summary injected.")
            else:
                chat.add_message("assistant", "Nothing to compact yet (< 10 messages).")

        # ── Export / Import ───────────────────────────

        elif command == "/export":
            sub = args.split(maxsplit=1)[0] if args else "all"
            sub_args = args[len(sub)+1:] if sub else ""
            exporter = Exporter()
            if sub == "list":
                exports = exporter.list_exports()
                if not exports:
                    chat.add_message("assistant", "No backups found.")
                else:
                    lines = ["**Backups:**"]
                    for e in exports:
                        size_kb = e["size"] // 1024
                        lines.append(f"  📄 {e['path']} ({e['label']}) — {size_kb}KB")
                    chat.add_message("assistant", "\n".join(lines))
            else:
                path = await exporter.export_all(label=sub_args)
                chat.add_message("assistant", f"✅ Exported to: `{path}`")

        elif command == "/import":
            if not args:
                chat.add_message("assistant", "Usage: `/import <path>` — Import from backup JSON file.\nUse `/export list` to see available backups.")
            else:
                exporter = Exporter()
                result = await exporter.import_file(args)
                chat.add_message("assistant", f"**Import result:**\n{result}")

        # ── Geo Tracker ─────────────────────────────

        elif command == "/geotrack":
            sub = args.split()[0] if args else "status"
            geo = get_geo()
            if sub == "now":
                result = await geo.force_update()
                if result:
                    chat.add_message("assistant", f"📍 Current location: {result}")
                else:
                    chat.add_message("assistant", "❌ Failed to detect location. Check internet connection.")
            else:
                st = geo.status
                lines = [
                    "**📍 Geo Tracker**",
                    f"  Last location: {st['last_location'] or 'never'}",
                    f"  Pages URL: {st.get('repo_published', 'not published')}",
                    f"  Check interval: {st['check_interval']}s",
                ]
                if st['last_gist_update']:
                    import time
                    mins_ago = int((time.time() - st['last_gist_update']) / 60)
                    lines.append(f"  Last gist update: {mins_ago}m ago")
                lines.append("")
                lines.append("**Commands:**")
                lines.append("  `/geotrack now` — Force immediate check + gist update")
                lines.append("  `/geotrack` — Show status")
                chat.add_message("assistant", "\n".join(lines))

        else:
            chat.add_message("assistant", f"Unknown command: `{command}`. Type `/help` for available commands.")

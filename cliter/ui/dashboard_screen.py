"""Dashboard Screen — system overview hub."""
import json
from textual.screen import ModalScreen
from textual.widgets import Static, Button, DataTable
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.binding import Binding
from textual import work

from cliter.proxy import manager as pm
from cliter.proxy import tracker
from cliter.proxy import strategy as strategy_engine
from cliter.proxy import monitor
from cliter.utils.paths import home_dir, skills_dir


class DashboardScreen(ModalScreen[None]):
    """Main system dashboard — shows everything at a glance.

    Keybindings:
        P - Provider Manager
        S - Strategy Settings
        R - Refresh
        Esc - Close
    """

    DEFAULT_CSS = """
    DashboardScreen {
        align: center middle;
    }
    DashboardScreen > #main-box {
        width: 95%;
        height: 90%;
        border: solid $accent;
        background: $surface;
    }
    #title-box {
        height: 3;
        padding: 0 1;
        border-bottom: solid $border;
        content-align: center middle;
    }
    ScrollableContainer {
        height: 1fr;
    }
    .section-title {
        padding: 0 1;
        text-style: bold;
        background: $boost;
    }
    .stat-grid {
        height: auto;
        padding: 0 1;
    }
    .stat-box {
        width: 1fr;
        height: 3;
        border: solid $border;
        padding: 0 1;
        margin: 0 1;
    }
    .stat-value {
        text-style: bold;
        content-align: center middle;
    }
    .stat-label {
        content-align: center middle;
    }
    DataTable {
        height: auto;
        max-height: 10;
        margin: 0 1;
    }
    #action-bar {
        height: 3;
        padding: 0 1;
        border-top: solid $border;
    }
    #action-bar Button {
        margin: 0 1;
    }
    #status-label {
        padding: 0 2;
        height: 1;
    }
    Button {
        min-width: 14;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
        Binding("p", "providers", "Providers", show=True),
        Binding("s", "strategy", "Strategy", show=True),
        Binding("r", "refresh", "Refresh", show=True),
    ]

    def compose(self):
        with Vertical(id="main-box"):
            yield Static("[bold]CliTer Dashboard[/bold]", id="title-box")
            yield Static("", id="status-label")
            with ScrollableContainer():
                # ── Status section ──
                yield Static("System Status", classes="section-title", id="s-status")
                yield Horizontal(classes="stat-grid", id="grid-status")
                # ── Providers section ──
                yield Static("Providers Overview", classes="section-title", id="s-providers")
                yield Horizontal(classes="stat-grid", id="grid-providers")
                yield DataTable(id="provider-mini-table", show_cursor=False)
                # ── Reliability section ──
                yield Static("Provider Reliability", classes="section-title", id="s-reliability")
                yield DataTable(id="reliability-table", show_cursor=False)
            with Horizontal(id="action-bar"):
                yield Button("📊 Providers (P)", id="btn-providers", variant="primary")
                yield Button("⚙️  Strategy (S)", id="btn-strategy")
                yield Button("🔄 Refresh (R)", id="btn-refresh")
                yield Button("✖ Close (Esc)", id="btn-close")

    async def on_mount(self):
        await self._refresh()

    @work
    async def _refresh(self):
        await self._update_status()
        await self._update_providers()
        await self._update_reliability()
        self._status("Dashboard refreshed", "green")

    # ── Status section ────────────────────────

    async def _update_status(self):
        grid = self.query_one("#grid-status", Horizontal)
        await grid.remove_children()

        strat_info = await strategy_engine.get_strategy_info()
        budget = await tracker.get_budget()
        try:
            mon_info = await monitor.get_monitor_status()
        except Exception:
            mon_info = {"running": False, "active": 0, "inactive": 0, "rate_limited": 0}

        items = [
            ("Strategy", strat_info.get("strategy", "auto")),
            ("Proxy", "🟢 On" if mon_info.get("running") else "🔴 Off"),
            ("Providers", f"{mon_info.get('active',0)} active, {mon_info.get('inactive',0)} inactive"),
            ("Budget", f"{budget.get('used',0)} / {budget.get('limit',0) if budget.get('limit',0) > 0 else '∞'}"),
            ("Rate-limited", str(mon_info.get("rate_limited", 0))),
            ("Connections", f"{strat_info.get('available',0)} ready"),
        ]

        for label, val in items:
            with grid:
                with Vertical(classes="stat-box"):
                    yield Static(val, classes="stat-value")
                    yield Static(label, classes="stat-label")

    # ── Providers section ─────────────────────

    async def _update_providers(self):
        grid = self.query_one("#grid-providers", Horizontal)
        await grid.remove_children()

        providers = await pm.list_providers()
        active = sum(1 for p in providers if p.get("is_active"))
        inactive = len(providers) - active
        total = len(providers)

        for label, val in [("Total", str(total)), ("Active", str(active)), ("Inactive", str(inactive))]:
            with grid:
                with Vertical(classes="stat-box"):
                    yield Static(val, classes="stat-value")
                    yield Static(label, classes="stat-label")

        table = self.query_one("#provider-mini-table", DataTable)
        table.clear()
        table.add_columns("Status", "Name", "Prefix", "Priority")
        for p in providers:
            icon = "🟢" if p.get("is_active") else "🔴"
            table.add_row(icon, p.get("name", ""), p.get("prefix", ""), str(p.get("priority", 0)))

    # ── Reliability section ───────────────────

    async def _update_reliability(self):
        table = self.query_one("#reliability-table", DataTable)
        table.clear()
        table.add_columns("Provider", "Success %", "Avg Latency", "Requests", "Last Seen")

        try:
            rels = await tracker.get_reliabilities()
        except Exception:
            rels = []

        if not rels:
            table.add_row("(no data)", "-", "-", "0", "-")
            return

        for r in rels[:8]:  # Show top 8
            pid = r.get("provider_id", "?")[:10]
            rate = f"{r.get('success_rate', 100):.0f}%"
            lat = f"{r.get('avg_latency_ms', 0):.0f}ms" if r.get('avg_latency_ms', 0) > 0 else "-"
            total_req = str(r.get("total_requests", 0))
            last = r.get("last_success", "") or r.get("last_failure", "")
            last_str = "-"
            if last:
                import time
                mins_ago = int((time.time() - last) / 60)
                last_str = f"{mins_ago}m ago" if mins_ago < 120 else f"{int(mins_ago/60)}h ago"
            table.add_row(pid, rate, lat, total_req, last_str)

    # ── Actions ───────────────────────────────

    def action_providers(self):
        from cliter.ui.provider_screen import ProviderManagerScreen
        self.app.push_screen(ProviderManagerScreen())

    def action_strategy(self):
        from cliter.ui.strategy_screen import StrategyScreen
        self.app.push_screen(StrategyScreen())

    def action_refresh(self):
        self._refresh()

    def action_close(self):
        self.dismiss(None)

    def _status(self, msg: str, color: str = "white"):
        self.query_one("#status-label", Static).update(f"[{color}]{msg}[/{color}]")

    def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id
        if bid == "btn-providers":
            self.action_providers()
        elif bid == "btn-strategy":
            self.action_strategy()
        elif bid == "btn-refresh":
            self.action_refresh()
        elif bid == "btn-close":
            self.action_close()

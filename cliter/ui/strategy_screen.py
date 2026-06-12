"""Strategy Settings Screen — configure model selection strategy + budget."""
from textual.screen import ModalScreen
from textual.widgets import Static, Button, Label, Input, RadioSet, RadioButton, Select
from textual.containers import Vertical, Horizontal, ScrollableContainer
from textual.binding import Binding
from textual import work

from cliter.proxy import strategy as strategy_engine
from cliter.proxy import tracker
from cliter.config import settings

STRATEGIES = ["auto", "manual", "fallback", "round_robin", "cheapest"]


class StrategyScreen(ModalScreen[None]):
    """TUI to configure strategy mode and daily budget.

    Keybindings:
        S - Save & Apply
        R - Refresh
        Esc - Close
    """

    DEFAULT_CSS = """
    StrategyScreen {
        align: center middle;
    }
    StrategyScreen > #main-box {
        width: 60;
        height: auto;
        border: solid $accent;
        background: $surface;
        padding: 1 2;
    }
    .section-title {
        text-style: bold;
        padding: 1 0;
        border-bottom: solid $border;
    }
    .field-row {
        height: auto;
        padding: 0 0 1 0;
    }
    .field-label {
        width: 20;
        padding: 1 0;
    }
    Input {
        width: 1fr;
    }
    Select {
        width: 1fr;
    }
    RadioSet {
        width: 1fr;
    }
    #status-label {
        height: 1;
        padding: 0;
    }
    Horizontal Button {
        margin: 0 1;
    }
    Button {
        min-width: 14;
    }
    .info-box {
        border: solid $border;
        padding: 0 1;
        margin: 0 0 1 0;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
        Binding("s", "save", "Save", show=True),
        Binding("r", "refresh", "Refresh", show=True),
    ]

    def compose(self):
        with Vertical(id="main-box"):
            yield Static("[bold]Strategy & Budget Settings[/bold]", id="title")
            yield Static("", id="status-label")

            yield Static("Model Selection Strategy", classes="section-title")
            yield Vertical(id="strategy-info", classes="info-box")
            yield RadioSet(*[(s.capitalize(), s) for s in STRATEGIES], id="strategy-radio")

            yield Static("Daily Token Budget", classes="section-title")
            with Horizontal(classes="field-row"):
                yield Static("Budget (tokens):", classes="field-label")
                yield Input(id="budget-input", placeholder="0 = unlimited")

            yield Static("Usage Summary", classes="section-title")
            yield Static("", id="usage-summary")

            with Horizontal():
                yield Button("💾 Save (S)", id="btn-save", variant="primary")
                yield Button("🔄 Refresh (R)", id="btn-refresh")
                yield Button("✖ Close (Esc)", id="btn-close")

    async def on_mount(self):
        await self._refresh()

    async def _refresh(self):
        strat_info = await strategy_engine.get_strategy_info()
        budget = await tracker.get_budget()

        # Strategy info box
        info = self.query_one("#strategy-info", Vertical)
        await info.remove_children()
        await info.mount(
            Static(f"Current: [bold]{strat_info.get('strategy','auto')}[/bold]"),
            Static(f"Available providers: {strat_info.get('available',0)} / {strat_info.get('total_connections',0)}"),
            Static(f"Rate-limited: {strat_info.get('rate_limited',0)}"),
        )

        # Strategy radio — select current
        current = strat_info.get("strategy", "auto")
        radio = self.query_one("#strategy-radio", RadioSet)
        for i, s in enumerate(STRATEGIES):
            if s == current:
                radio.index = i
                break

        # Budget input
        budget_input = self.query_one("#budget-input", Input)
        limit = budget.get("limit", 0)
        budget_input.value = str(limit) if limit > 0 else ""

        # Usage summary
        usage_text = (f"Today: [bold]{budget.get('used',0)}[/bold] tokens used"
                      f" out of [bold]{limit if limit > 0 else 'unlimited'}[/bold]")
        self.query_one("#usage-summary", Static).update(usage_text)

    # ── Actions ───────────────────────────────

    @work
    async def action_save(self):
        try:
            # Strategy
            radio = self.query_one("#strategy-radio", RadioSet)
            selected_idx = radio.index
            if 0 <= selected_idx < len(STRATEGIES):
                new_strategy = STRATEGIES[selected_idx]
                settings.set_val("strategy", "mode", value=new_strategy)
                self._status(f"Strategy set to: {new_strategy}", "green")

            # Budget
            budget_input = self.query_one("#budget-input", Input)
            budget_val = budget_input.value.strip()
            if budget_val:
                try:
                    budget_int = int(budget_val)
                    if budget_int >= 0:
                        settings.set_val("budget", "daily_limit", value=str(budget_int))
                        # Reinitialize budget tracker with new limit
                        await tracker.set_budget(budget_int)
                        self._status(f"Budget set to {budget_int} tokens/day{' (unlimited)' if budget_int == 0 else ''}", "green")
                    else:
                        self._status("Budget must be >= 0", "red")
                        return
                except ValueError:
                    self._status("Invalid budget number", "red")
                    return
            else:
                # Clear = unlimited
                settings.set_val("budget", "daily_limit", value="0")
                await tracker.set_budget(0)
                self._status("Budget set to unlimited", "green")

            await self._refresh()
        except Exception as e:
            self._status(f"Error: {e}", "red")

    def action_refresh(self):
        self._refresh()

    def action_close(self):
        self.dismiss(None)

    def _status(self, msg: str, color: str = "white"):
        self.query_one("#status-label", Static).update(f"[{color}]{msg}[/{color}]")

    def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id
        if bid == "btn-save":
            self.action_save()
        elif bid == "btn-refresh":
            self.action_refresh()
        elif bid == "btn-close":
            self.action_close()

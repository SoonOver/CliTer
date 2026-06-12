"""Provider Manager — full TUI screen for managing proxy providers."""
import json
import time
import aiosqlite
from textual.screen import ModalScreen
from textual.widgets import Static, Button, Label, Input, DataTable
from textual.containers import Vertical, Horizontal
from textual.binding import Binding
from textual import work

from cliter.proxy import manager as pm
from cliter.proxy.manager import DB
from cliter.ui.modal import ConfirmModal


class ProviderForm(ModalScreen[dict | None]):
    """Form modal for adding/editing a provider."""

    DEFAULT_CSS = """
    ProviderForm {
        align: center middle;
    }
    ProviderForm > Vertical {
        width: 74;
        height: auto;
        border: solid $accent;
        padding: 1 2;
        background: $surface;
    }
    ProviderForm Input {
        width: 1fr;
        margin-bottom: 1;
    }
    ProviderForm .row {
        height: auto;
    }
    ProviderForm .label {
        width: 16;
        padding: 1 0;
    }
    """

    def __init__(self, provider: dict = None, **kwargs):
        super().__init__(**kwargs)
        self.provider = provider

    def compose(self):
        title = "Edit Provider" if self.provider else "Add Provider"
        p = self.provider or {}
        with Vertical():
            yield Static(f"[bold]{title}[/bold]", id="form-title")
            with Horizontal(classes="row"):
                yield Static("Name:", classes="label")
                yield Input(value=p.get("name", ""), id="f-name", placeholder="OpenRouter")
            with Horizontal(classes="row"):
                yield Static("Prefix:", classes="label")
                yield Input(value=p.get("prefix", ""), id="f-prefix", placeholder="or")
            with Horizontal(classes="row"):
                yield Static("Base URL:", classes="label")
                yield Input(value=p.get("base_url", ""), id="f-url", placeholder="https://api.openai.com/v1")
            with Horizontal(classes="row"):
                yield Static("API Key:", classes="label")
                yield Input(value=p.get("api_key", ""), id="f-key", placeholder="sk-...", password=True)
            with Horizontal(classes="row"):
                yield Static("Models:", classes="label")
                yield Input(value=p.get("models", ""), id="f-models", placeholder="gpt-4o, gpt-4o-mini")
            with Horizontal(classes="row"):
                yield Static("Priority:", classes="label")
                yield Input(value=str(p.get("priority", 5)), id="f-priority", placeholder="0-100")
            with Horizontal():
                yield Button("Save", id="save", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "save":
            self._save()

    def _save(self):
        name = self.query_one("#f-name", Input).value.strip()
        prefix = self.query_one("#f-prefix", Input).value.strip()
        url = self.query_one("#f-url", Input).value.strip()
        key = self.query_one("#f-key", Input).value.strip()
        models_str = self.query_one("#f-models", Input).value.strip()
        priority_str = self.query_one("#f-priority", Input).value.strip()

        if not name or not prefix or not url:
            self.query_one("#form-title", Static).update(
                "[bold red]Name, Prefix, and Base URL required![/bold red]"
            )
            return

        try:
            priority = int(priority_str) if priority_str else 5
        except ValueError:
            priority = 5

        models = [m.strip() for m in models_str.split(",") if m.strip()]

        self.dismiss({
            "name": name,
            "prefix": prefix,
            "base_url": url,
            "api_key": key,
            "models": models,
            "priority": priority,
        })


class ProviderManagerScreen(ModalScreen[None]):
    """Full TUI screen to manage proxy providers.

    Keybindings:
        A - Add provider
        E - Edit selected
        D - Delete selected
        T - Toggle active/inactive
        F5 - Refresh list
        Esc - Close
    """

    DEFAULT_CSS = """
    ProviderManagerScreen {
        align: center middle;
    }
    ProviderManagerScreen > #main-box {
        width: 95%;
        height: 90%;
        border: solid $accent;
        background: $surface;
    }
    #header-box {
        height: 3;
        padding: 0 1;
        border-bottom: solid $border;
        content-align: center middle;
    }
    DataTable {
        height: 1fr;
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
        min-width: 12;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
        Binding("a", "add", "Add", show=True),
        Binding("e", "edit", "Edit", show=True),
        Binding("d", "delete", "Delete", show=True),
        Binding("t", "toggle", "Toggle", show=True),
        Binding("f5", "refresh", "Refresh", show=True),
    ]

    def compose(self):
        with Vertical(id="main-box"):
            yield Static("[bold]Provider Manager[/bold]", id="header-box")
            yield Static("", id="status-label")
            yield DataTable(id="provider-table")
            with Horizontal(id="action-bar"):
                yield Button("➕ Add (A)", id="btn-add", variant="primary")
                yield Button("✏️ Edit (E)", id="btn-edit")
                yield Button("🗑️ Del (D)", id="btn-delete", variant="error")
                yield Button("⏻ Toggle (T)", id="btn-toggle")
                yield Button("🔄 Refresh (F5)", id="btn-refresh")
                yield Button("✖ Close (Esc)", id="btn-close")

    async def on_mount(self):
        table = self.query_one("#provider-table", DataTable)
        table.add_columns("Active", "Name", "Prefix", "Base URL", "Models", "Priority", "Key")
        await self._reload_table()

    # ── Data loading ──────────────────────────

    async def _reload_table(self):
        table = self.query_one("#provider-table", DataTable)
        table.clear()
        providers = await pm.list_providers()

        if not providers:
            self.query_one("#status-label", Static).update("[dim]No providers configured[/dim]")
            return

        for p in providers:
            active = "🟢" if p.get("is_active") else "🔴"
            try:
                raw = p.get("models", "[]")
                models_list = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                models_list = []
            ms = ", ".join(models_list[:3])
            if len(models_list) > 3:
                ms += f"...(+{len(models_list)-3})"
            k = (p.get("api_key") or "")[:10] + "..." if p.get("api_key") else "-"
            table.add_row(
                active,
                p.get("name", ""),
                p.get("prefix", ""),
                p.get("base_url", ""),
                ms,
                str(p.get("priority", 0)),
                k,
            )

        self.query_one("#status-label", Static).update(
            f"[dim]{len(providers)} provider(s) — arrow keys to navigate, A/E/D/T to act[/dim]"
        )

    # ── Actions ──────────────────────────────

    def _selected_idx(self) -> int | None:
        table = self.query_one("#provider-table", DataTable)
        return table.cursor_row

    def action_add(self):
        self._show_form()

    def action_edit(self):
        idx = self._selected_idx()
        if idx is None:
            self._status("Select a provider first", "yellow")
            return
        self._show_form(edit_idx=idx)

    @work
    async def action_delete(self):
        idx = self._selected_idx()
        if idx is None:
            self._status("Select a provider first", "yellow")
            return
        providers = await pm.list_providers()
        if idx >= len(providers):
            return
        p = providers[idx]
        confirmed = await self.app.push_screen_wait(ConfirmModal(f"Delete '{p['name']}'?"))
        if not confirmed:
            return
        ok = await pm.delete_provider(p["id"])
        if ok:
            self._status(f"Deleted {p['name']}", "green")
        else:
            self._status(f"Failed to delete {p['name']}", "red")
        await self._reload_table()

    @work
    async def action_toggle(self):
        idx = self._selected_idx()
        if idx is None:
            self._status("Select a provider first", "yellow")
            return
        providers = await pm.list_providers()
        if idx >= len(providers):
            return
        p = providers[idx]
        new = not p["is_active"]
        await pm.set_active(p["id"], new)
        self._status(f"{p['name']} {'enabled' if new else 'disabled'}", "green")
        await self._reload_table()

    @work
    async def action_refresh(self):
        await self._reload_table()
        self._status("Refreshed", "green")

    def action_close(self):
        self.dismiss(None)

    # ── Form (Add / Edit) ────────────────────

    @work
    async def _show_form(self, edit_idx: int | None = None):
        providers = await pm.list_providers()
        form_data = None
        if edit_idx is not None:
            if edit_idx >= len(providers):
                return
            p = providers[edit_idx]
            try:
                raw = p.get("models", "[]")
                models_list = json.loads(raw) if isinstance(raw, str) else raw
            except Exception:
                models_list = []
            form_data = {
                "name": p["name"],
                "prefix": p["prefix"],
                "base_url": p["base_url"],
                "api_key": p.get("api_key", ""),
                "models": ", ".join(models_list),
                "priority": p.get("priority", 5),
            }

        result = await self.app.push_screen_wait(ProviderForm(provider=form_data))
        if result is None:
            return  # cancelled

        try:
            if edit_idx is not None:
                target_id = providers[edit_idx]["id"]
                async with aiosqlite.connect(DB) as db:
                    await db.execute(
                        "UPDATE proxy_providers SET prefix=?, base_url=?, api_key=?, models=?, priority=?, updated_at=? WHERE id=?",
                        (result["prefix"], result["base_url"], result["api_key"],
                         json.dumps(result["models"]), result["priority"], time.time(), target_id)
                    )
                    await db.commit()
                self._status(f"Updated {result['name']}", "green")
            else:
                # Add new
                await pm.add_provider(
                    name=result["name"],
                    prefix=result["prefix"],
                    base_url=result["base_url"],
                    api_key=result["api_key"],
                    models=result["models"],
                    priority=result["priority"],
                )
                self._status(f"Added {result['name']}", "green")
        except Exception as e:
            self._status(f"Error: {e}", "red")

        await self._reload_table()

    # ── Helpers ──────────────────────────────

    def _status(self, msg: str, color: str = "white"):
        self.query_one("#status-label", Static).update(f"[{color}]{msg}[/{color}]")

    # ── Button handlers ──────────────────────

    def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id
        if bid == "btn-add":
            self.action_add()
        elif bid == "btn-edit":
            self.action_edit()
        elif bid == "btn-delete":
            self.action_delete()
        elif bid == "btn-toggle":
            self.action_toggle()
        elif bid == "btn-refresh":
            self.action_refresh()
        elif bid == "btn-close":
            self.action_close()

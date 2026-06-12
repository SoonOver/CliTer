"""Memory Viewer — compact popup screen for viewing/editing agent memories.

Designed for Termux: half-height, scrollable, close with Escape.
"""
from textual.screen import ModalScreen
from textual.widgets import Static, Button, Input, DataTable
from textual.containers import Vertical, Horizontal
from textual.binding import Binding

from cliter.core import memory


class MemoryScreen(ModalScreen[None]):
    """Compact memory viewer — view, add, edit, delete memory entries."""

    DEFAULT_CSS = """
    MemoryScreen {
        align: center middle;
    }
    #memory-box {
        width: 80%;
        height: 60%;
        border: solid $accent;
        background: $surface;
    }
    #memory-header {
        height: 3;
        padding: 0 1;
        border-bottom: solid $border;
        content-align: center middle;
    }
    DataTable {
        height: 1fr;
        margin: 0 1;
    }
    #memory-input-row {
        height: 3;
        padding: 0 1;
        border-top: solid $border;
    }
    #memory-input-row Input {
        width: 1fr;
        height: 3;
    }
    #memory-input-row Button {
        width: 10;
        height: 3;
        margin: 0 1;
    }
    #memory-actions {
        height: 3;
        padding: 0 1;
        border-top: solid $border;
        align: center middle;
    }
    #memory-actions Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
        Binding("delete", "delete_selected", "Delete", show=False),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._selected_entry: tuple | None = None

    def compose(self):
        with Vertical(id="memory-box"):
            yield Static("[bold]🧠 Memory Viewer[/bold]", id="memory-header")
            yield DataTable(id="memory-table", cursor_type="row")
            with Horizontal(id="memory-input-row"):
                yield Input(id="memory-new-key", placeholder="Key (e.g. project_name)")
                yield Input(id="memory-new-val", placeholder="Value")
                yield Button("➕ Add", id="btn-mem-add", variant="primary")
            with Horizontal(id="memory-actions"):
                yield Button("🗑 Delete Selected", id="btn-mem-del")
                yield Button("🔄 Refresh", id="btn-mem-refresh")
                yield Button("✖ Close (Esc)", id="btn-close")

    async def on_mount(self):
        await self._refresh()

    async def _refresh(self):
        table = self.query_one("#memory-table", DataTable)
        table.clear()
        table.add_columns("ID", "Category", "Content")

        entries = await memory.list_all()
        for e in entries:
            c = e["content"]
            table.add_row(str(e["id"]), e["category"], c[:60] + ("..." if len(c) > 60 else ""))

    async def on_data_table_row_selected(self, event: DataTable.RowSelected):
        table = self.query_one("#memory-table", DataTable)
        try:
            row = table.get_row(event.row_key.value)
            self._selected_entry = {"id": int(row[0]), "category": row[1], "content": row[2]}
        except Exception:
            pass

    async def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id
        if bid == "btn-mem-add":
            await self._add_entry()
        elif bid == "btn-mem-del":
            await self._delete_selected()
        elif bid == "btn-mem-refresh":
            await self._refresh()
        elif bid == "btn-close":
            self.dismiss(None)

    async def _add_entry(self):
        key = self.query_one("#memory-new-key", Input).value.strip()
        val = self.query_one("#memory-new-val", Input).value.strip()
        if key and val:
            await memory.add(content=val, category=key)
            self.query_one("#memory-new-key", Input).value = ""
            self.query_one("#memory-new-val", Input).value = ""
            await self._refresh()
            try:
                self.app.notify("Memory added", "success")
            except Exception:
                pass

    async def _delete_selected(self):
        if self._selected_entry:
            mem_id = self._selected_entry["id"]
            cat = self._selected_entry["category"]
            await memory.remove(mem_id)
            self._selected_entry = None
            await self._refresh()
            try:
                self.app.notify(f"Deleted: {cat}", "info")
            except Exception:
                pass

    def action_close(self):
        self.dismiss(None)

    def action_delete_selected(self):
        self.run_worker(self._delete_selected())

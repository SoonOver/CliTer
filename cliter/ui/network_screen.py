"""Network Scanner Screen — compact device list for Termux."""
from textual.screen import ModalScreen
from textual.widgets import Static, Button, DataTable
from textual.containers import Vertical, Horizontal
from textual.binding import Binding

from cliter.services.net_scanner import get_scanner


class NetworkScreen(ModalScreen[None]):
    """Compact network scanner display — devices on local network."""

    DEFAULT_CSS = """
    NetworkScreen {
        align: center middle;
    }
    #net-box {
        width: 90%;
        height: 70%;
        border: solid $accent;
        background: $surface;
    }
    #net-header {
        height: 3;
        padding: 0 1;
        border-bottom: solid $border;
        content-align: center middle;
    }
    DataTable {
        height: 1fr;
        margin: 0 1;
    }
    #net-footer {
        height: 3;
        padding: 0 1;
        border-top: solid $border;
        align: center middle;
    }
    #net-footer Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
        Binding("r", "refresh", "Refresh", show=True),
    ]

    def compose(self):
        with Vertical(id="net-box"):
            yield Static("[bold]📡 Network Scanner[/bold]", id="net-header")
            yield DataTable(id="net-table", show_cursor=False)
            with Horizontal(id="net-footer"):
                yield Button("🔄 Scan", id="btn-scan", variant="primary")
                yield Button("✖ Close (Esc)", id="btn-close")

    async def on_mount(self):
        await self._scan()

    async def _scan(self):
        table = self.query_one("#net-table", DataTable)
        table.clear()
        table.add_columns("Status", "IP", "MAC", "Vendor", "Hostname")

        scanner = get_scanner()
        devices = await scanner.scan()

        for d in devices:
            icon = "🟢" if d.online else "🔴"
            hostname = d.hostname[:15] if d.hostname and d.hostname != "?" else "?"
            table.add_row(icon, d.ip, d.mac, d.vendor, hostname, height=1)

        total = len(devices)
        online = sum(1 for d in devices if d.online)
        header = self.query_one("#net-header", Static)
        header.update(f"[bold]📡 Network Scanner[/bold] — {online}/{total} devices online")

    async def on_button_pressed(self, event: Button.Pressed):
        bid = event.button.id
        if bid == "btn-scan":
            await self._scan()
        elif bid == "btn-close":
            self.dismiss(None)

    def action_close(self):
        self.dismiss(None)

    def action_refresh(self):
        self.run_worker(self._scan())

"""Status bar — model, tokens, session info, quick toggles."""
from textual.widgets import Static
from textual import events


class StatusBar(Static):
    """Bottom status bar — clickable provider status, model, session."""

    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    StatusBar:hover {
        background: $accent 15%;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._model = "gpt-4o-mini"
        self._session = "New Chat"
        self._status = "Ready"
        self._providers = "0 active"

    def on_mount(self):
        self._render()

    def set_model(self, model: str):
        self._model = model
        self._render()

    def set_session(self, name: str):
        self._session = name
        self._render()

    def set_status(self, status: str):
        self._status = status
        self._render()

    def set_providers(self, text: str):
        self._providers = text
        self._render()

    def _render(self):
        proxy_indicator = ""
        app = self.app if hasattr(self, 'app') else None
        if app and hasattr(app, '_proxy_server') and app._proxy_server and app._proxy_server.running:
            proxy_indicator = " 🔄"
        self.update(
            f" 🤖 {self._model}{proxy_indicator}  │  💬 {self._session}  │  🔌 {self._providers}  │  {self._status}"
        )

    def on_click(self):
        """Click status bar → open Dashboard."""
        try:
            from cliter.ui.dashboard_screen import DashboardScreen
            self.app.push_screen(DashboardScreen())
        except Exception:
            pass

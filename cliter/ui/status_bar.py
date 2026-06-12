"""Status bar — model, tokens, session info."""
from textual.widgets import Static


class StatusBar(Static):
    """Bottom status bar."""

    DEFAULT_CSS = """
    StatusBar {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._model = "gpt-4o-mini"
        self._session = "New Chat"
        self._status = "Ready"

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

    def _render(self):
        proxy_indicator = ""
        # check if proxy server is running
        app = self.app if hasattr(self, 'app') else None
        if app and hasattr(app, '_proxy_server') and app._proxy_server and app._proxy_server.running:
            proxy_indicator = " 🔄"
        self.update(f" 🤖 {self._model}{proxy_indicator}  │  💬 {self._session}  │  {self._status}")

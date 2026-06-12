"""Action bar — clickable quick-action buttons."""
from textual.widgets import Static, Button
from textual.containers import Horizontal
from textual.app import App


class ActionButton(Button):
    """Single action button with emoji label."""

    def __init__(self, label: str, action: str, **kwargs):
        super().__init__(label, **kwargs)
        self.action_name = action


class ActionBar(Horizontal):
    """Horizontal bar of clickable action buttons for quick commands."""

    DEFAULT_CSS = """
    ActionBar {
        height: 3;
        dock: bottom;
        padding: 0 1;
        border-top: solid $border;
        background: $surface;
        align: center middle;
    }
    ActionBar ActionButton {
        min-width: 10;
        max-width: 18;
        height: 3;
        margin: 0 1;
    }
    ActionBar ActionButton:hover {
        text-style: bold;
        background: $accent 30%;
    }
    """

    def compose(self):
        yield ActionButton("📊 Dashboard", "dashboard")
        yield ActionButton("🔧 Providers", "providers")
        yield ActionButton("⚙️ Strategy", "strategy")
        yield ActionButton("📍 Map", "geotrack")
        yield ActionButton("🆕 New Chat", "new_session")
        yield ActionButton("❓ Help", "help")
        yield ActionButton("🗑 Clear", "clear")

    def on_button_pressed(self, event: Button.Pressed):
        btn = event.button
        if hasattr(btn, "action_name"):
            action = btn.action_name
            app = self.app
            if hasattr(app, f"action_quick_{action}"):
                getattr(app, f"action_quick_{action}")()

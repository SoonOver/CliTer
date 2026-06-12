"""Search bar — compact overlay for searching chat messages."""
from textual.widgets import Static, Input
from textual.containers import Horizontal
from textual.binding import Binding


class SearchBar(Horizontal):
    """Compact search bar for chat — Ctrl+F to open, type to search."""

    DEFAULT_CSS = """
    SearchBar {
        height: 3;
        dock: bottom;
        border-top: solid $accent;
        background: $surface;
        padding: 0 1;
        display: none;
    }
    SearchBar.-visible {
        display: block;
    }
    SearchBar > #search-input {
        width: 1fr;
        height: 3;
    }
    SearchBar > #search-count {
        width: 10;
        height: 3;
        content-align: center middle;
        color: $text-muted;
    }
    SearchBar > #search-close {
        width: 3;
        height: 3;
        content-align: center middle;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("up", "prev_match", "Prev", show=False),
        Binding("down", "next_match", "Next", show=False),
        Binding("escape", "close", "Close", show=False),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._matches: list = []
        self._current_match = -1

    def compose(self):
        yield Input(id="search-input", placeholder="🔍 Search messages...")
        yield Static("0/0", id="search-count")
        yield Static("✕", id="search-close")

    def toggle(self):
        self.toggle_class("-visible")
        if self.has_class("-visible"):
            inp = self.query_one("#search-input", Input)
            inp.focus()
            inp.value = ""
        else:
            self._clear_highlights()

    def on_input_changed(self, event: Input.Changed):
        if event.input.id == "search-input":
            self._search(event.value)

    def on_static_clicked(self, event: Static.Clicked):
        if event.static.id == "search-close":
            self.toggle()

    def _search(self, query: str):
        """Search through chat messages and highlight matches."""
        self._clear_highlights()
        self._matches = []
        self._current_match = -1

        if not query.strip():
            self.query_one("#search-count", Static).update("0/0")
            return

        from cliter.ui.chat_panel import ChatPanel, ChatMessage
        chat = self.app.query_one(ChatPanel)
        children = list(chat.children)
        query_lower = query.lower()

        for i, child in enumerate(children):
            if isinstance(child, ChatMessage) and query_lower in child.msg_content.lower():
                self._matches.append(i)
                child.set_class(True, "-search-match")

        total = len(self._matches)
        if total > 0:
            self._current_match = 0
            self._focus_match(0)
        self.query_one("#search-count", Static).update(f"{min(self._current_match+1, 1)}/{total}" if total > 0 else "0/0")

    def _focus_match(self, idx: int):
        """Highlight and scroll to a specific match."""
        from cliter.ui.chat_panel import ChatPanel, ChatMessage
        chat = self.app.query_one(ChatPanel)
        children = list(chat.children)

        for i, c in enumerate(children):
            if isinstance(c, ChatMessage):
                c.set_class(i == self._matches[idx], "-search-active")
                c.set_class(i != self._matches[idx] and c.has_class("-search-match"), "-search-match")

        target = children[self._matches[idx]]
        target.call_after_refresh(target.scroll_visible, top=True)

    def action_close(self):
        self.toggle()

    def action_next_match(self):
        if self._matches:
            self._current_match = (self._current_match + 1) % len(self._matches)
            self._focus_match(self._current_match)
            self.query_one("#search-count", Static).update(f"{self._current_match+1}/{len(self._matches)}")

    def action_prev_match(self):
        if self._matches:
            self._current_match = (self._current_match - 1) % len(self._matches)
            self._focus_match(self._current_match)
            self.query_one("#search-count", Static).update(f"{self._current_match+1}/{len(self._matches)}")

    def _clear_highlights(self):
        from cliter.ui.chat_panel import ChatPanel, ChatMessage
        try:
            chat = self.app.query_one(ChatPanel)
            for child in chat.children:
                if isinstance(child, ChatMessage):
                    child.remove_class("-search-match", "-search-active")
        except Exception:
            pass

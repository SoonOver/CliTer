"""Input box — user text input with history."""
from textual.widgets import TextArea
from textual import events


class InputBox(TextArea):
    """Multi-line input. Ctrl+Enter to send, Enter for newline."""

    DEFAULT_CSS = """
    InputBox {
        height: auto;
        min-height: 3;
        max-height: 10;
        border: solid $accent;
        padding: 0 1;
    }
    InputBox:focus {
        border: solid $primary;
    }
    """

    def __init__(self, **kwargs):
        super().__init__(language=None, **kwargs)
        self._history: list[str] = []
        self._history_idx: int = -1

    def _on_key(self, event: events.Key):
        # Ctrl+Enter → send
        if event.key == "ctrl+j" or (event.key == "enter" and event.ctrl):
            event.prevent_default()
            event.stop()
            text = self.text.strip()
            if text:
                self._history.append(text)
                self._history_idx = -1
                self.post_message(self.Submitted(self, text))
                self.clear()
            return

        # Up arrow at empty → history
        if event.key == "up" and not self.text.strip():
            if self._history:
                self._history_idx = max(0, len(self._history) - 1 if self._history_idx == -1 else self._history_idx - 1)
                self.text = self._history[self._history_idx]
            event.prevent_default()
            return

    class Submitted(TextArea.Changed):
        """Posted when user submits input."""
        def __init__(self, text_area, value: str):
            super().__init__(text_area)
            self.value = value

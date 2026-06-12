"""Toast notifications — small auto-dismiss popups for background events."""
import asyncio
from textual.widgets import Static
from textual.containers import Container


class Toast(Static):
    """Single toast notification message."""

    DEFAULT_CSS = """
    Toast {
        padding: 0 2;
        min-height: 1;
        background: $surface;
        border: solid $accent;
        color: $text;
    }
    """


class ToastContainer(Container):
    """Stack of toast notifications at bottom-right corner.

    Minimal screen space — toasts are thin, stack upward, auto-dismiss.
    Geotracker notifications are filtered out.
    """

    DEFAULT_CSS = """
    ToastContainer {
        position: fixed;
        dock: bottom;
        layer: overlay;
        width: 50%;
        height: auto;
        max-height: 10;
        align-horizontal: right;
        align-vertical: bottom;
        padding: 0 1 1 0;
        pointer-events: none;
    }
    Toast {
        margin: 0 0 1 0;
        padding: 0 1;
        min-height: 1;
        background: $surface;
        border: solid $accent;
        color: $text;
        text-style: bold;
        width: 100%;
    }
    Toast.-error {
        border: solid $error;
    }
    Toast.-success {
        border: solid $success;
    }
    """

    _FILTER_WORDS = ["geotrack", "geo tracker", "location"]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._queue: list[str] = []
        self._showing = False

    def notify(self, message: str, toast_type: str = "info"):
        """Queue a toast notification. Filters geotracker messages."""
        msg_lower = message.lower()
        for word in self._FILTER_WORDS:
            if word in msg_lower:
                return  # Silently drop geotracker notifications

        self._queue.append((message, toast_type))
        if not self._showing:
            self._show_next()

    def _show_next(self):
        if not self._queue:
            self._showing = False
            return
        self._showing = True
        msg, ttype = self._queue.pop(0)
        toast = Toast(msg)
        if ttype == "error":
            toast.add_class("-error")
        elif ttype == "success":
            toast.add_class("-success")
        self.mount(toast)
        asyncio.create_task(self._dismiss(toast))

    async def _dismiss(self, toast: Toast, delay: float = 3.0):
        await asyncio.sleep(delay)
        try:
            toast.remove()
        except Exception:
            pass
        self._show_next()

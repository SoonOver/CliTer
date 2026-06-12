"""Chat panel — scrollable message display."""
from textual.widgets import Static, RichLog
from textual.containers import VerticalScroll
from rich.markdown import Markdown
from rich.text import Text


class ChatMessage(Static):
    """Single chat message — clickable."""

    DEFAULT_CSS = """
    ChatMessage {
        margin: 0 0 1 0;
        padding: 0 1;
    }
    ChatMessage:hover {
        background: $accent 15%;
    }
    ChatMessage.-search-match {
        border-left: solid $warning;
    }
    ChatMessage.-search-active {
        background: $warning 25%;
        border-left: solid $warning;
    }
    """

    def __init__(self, role: str, content: str, **kwargs):
        super().__init__(**kwargs)
        self.role = role
        self.msg_content = content

    def compose(self):
        yield from []

    def on_mount(self):
        if self.role == "user":
            prefix = Text("You > ", style="bold cyan")
        elif self.role == "assistant":
            prefix = Text("CliTer > ", style="bold green")
        elif self.role == "tool":
            prefix = Text("Tool > ", style="bold yellow")
        else:
            prefix = Text(f"{self.role} > ", style="bold")

        try:
            md = Markdown(self.msg_content)
            self.update(md)
        except Exception:
            self.update(self.msg_content)

    def on_click(self):
        """Click message: user → copy to input, assistant → copy to clipboard."""
        from cliter.ui.input_box import InputBox
        try:
            inp = self.app.query_one(InputBox)
            if self.role == "user":
                inp.text = self.msg_content
                inp.focus()
            elif self.role == "assistant":
                # Copy to clipboard
                import pyperclip
                try:
                    pyperclip.copy(self.msg_content)
                except Exception:
                    pass
                sb = self.app.query_one("StatusBar")
                if sb:
                    sb.set_status("Copied!")
        except Exception:
            pass


class ChatPanel(VerticalScroll):
    """Scrollable chat message area."""

    DEFAULT_CSS = """
    ChatPanel {
        height: 1fr;
        padding: 0 1;
        scrollbar-size: 1 1;
    }
    ChatMessage {
        margin: 0 0 1 0;
        padding: 0 1;
    }
    """

    def add_message(self, role: str, content: str):
        msg = ChatMessage(role, content)
        self.mount(msg)
        self.call_after_refresh(self.scroll_end, animate=False)

    def update_last_assistant(self, content: str):
        """Update the last assistant message (for streaming)."""
        children = list(self.children)
        for child in reversed(children):
            if isinstance(child, ChatMessage) and child.role == "assistant":
                try:
                    child.msg_content = content
                    md = Markdown(content)
                    child.update(md)
                except Exception:
                    child.update(content)
                self.call_after_refresh(self.scroll_end, animate=False)
                return
        # no existing assistant message, create one
        self.add_message("assistant", content)

    def clear_chat(self):
        self.remove_children()

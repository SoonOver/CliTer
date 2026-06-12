"""Modal dialogs — confirmation, input, selection."""
from textual.screen import ModalScreen
from textual.widgets import Static, Button, Input, Label
from textual.containers import Vertical, Horizontal


class ConfirmModal(ModalScreen[bool]):
    """Yes/No confirmation dialog."""

    DEFAULT_CSS = """
    ConfirmModal {
        align: center middle;
    }
    ConfirmModal > Vertical {
        width: 50;
        height: auto;
        border: solid $accent;
        padding: 1 2;
        background: $surface;
    }
    """

    def __init__(self, message: str, **kwargs):
        super().__init__(**kwargs)
        self.message = message

    def compose(self):
        with Vertical():
            yield Label(self.message)
            with Horizontal():
                yield Button("Yes", id="yes", variant="primary")
                yield Button("No", id="no")

    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss(event.button.id == "yes")


class InputModal(ModalScreen[str]):
    """Text input dialog."""

    DEFAULT_CSS = """
    InputModal {
        align: center middle;
    }
    InputModal > Vertical {
        width: 60;
        height: auto;
        border: solid $accent;
        padding: 1 2;
        background: $surface;
    }
    """

    def __init__(self, prompt: str, default: str = "", **kwargs):
        super().__init__(**kwargs)
        self.prompt = prompt
        self.default_val = default

    def compose(self):
        with Vertical():
            yield Label(self.prompt)
            yield Input(value=self.default_val, id="modal-input")
            with Horizontal():
                yield Button("OK", id="ok", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_button_pressed(self, event: Button.Pressed):
        if event.button.id == "ok":
            inp = self.query_one("#modal-input", Input)
            self.dismiss(inp.value)
        else:
            self.dismiss("")

    def on_input_submitted(self, event: Input.Submitted):
        self.dismiss(event.value)

"""Sidebar — sessions, tools, skills tabs."""
from textual.widgets import Static, ListView, ListItem, Label, TabbedContent, TabPane
from textual.containers import Vertical


class SessionItem(ListItem):
    """Session list item — click to switch, right-click for menu."""

    DEFAULT_CSS = """
    SessionItem:hover {
        background: $accent 20%;
    }
    """

    def __init__(self, session_id: str, title: str, active: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.session_id = session_id
        self.session_title = title
        self.active = active

    def compose(self):
        prefix = "📍" if self.active else "💬"
        yield Label(f"{prefix} {self.session_title}")

    def on_click(self):
        """Left click — let parent ListView handle switching."""
        pass


class ToolItem(ListItem):
    def __init__(self, name: str, desc: str, **kwargs):
        super().__init__(**kwargs)
        self.tool_name = name
        self.tool_desc = desc

    def compose(self):
        yield Label(f"🔧 {self.tool_name}")


class SkillItem(ListItem):
    def __init__(self, name: str, **kwargs):
        super().__init__(**kwargs)
        self.skill_name = name

    def compose(self):
        yield Label(f"📚 {self.skill_name}")


class Sidebar(Vertical):
    """Collapsible sidebar with tabs: Sessions, Tools, Skills."""

    DEFAULT_CSS = """
    Sidebar {
        width: 30;
        dock: left;
        border-right: solid $border;
        padding: 0;
    }
    Sidebar.-hidden {
        display: none;
    }
    """

    def compose(self):
        with TabbedContent("Sessions", "Tools", "Skills"):
            with TabPane("Sessions"):
                yield ListView(id="session-list")
            with TabPane("Tools"):
                yield ListView(id="tool-list")
            with TabPane("Skills"):
                yield ListView(id="skill-list")

    def toggle(self):
        self.toggle_class("-hidden")

    async def refresh_sessions(self, sessions: list[dict], active_id: str = ""):
        lv = self.query_one("#session-list", ListView)
        await lv.clear()
        for s in sessions:
            is_active = s["id"] == active_id
            await lv.append(SessionItem(s["id"], s.get("title", "Untitled"), active=is_active))

    async def refresh_tools(self, tools: list):
        lv = self.query_one("#tool-list", ListView)
        await lv.clear()
        for t in tools:
            await lv.append(ToolItem(t.name, t.description))

    async def refresh_skills(self, skills: list[dict]):
        lv = self.query_one("#skill-list", ListView)
        await lv.clear()
        for s in skills:
            await lv.append(SkillItem(s.get("name", "?")))

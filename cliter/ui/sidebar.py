"""Sidebar — sessions, tools, skills tabs."""
from textual.widgets import Static, ListView, ListItem, Label, TabbedContent, TabPane
from textual.containers import Vertical


class SessionItem(ListItem):
    def __init__(self, session_id: str, title: str, **kwargs):
        super().__init__(**kwargs)
        self.session_id = session_id
        self.session_title = title

    def compose(self):
        yield Label(f"💬 {self.session_title}")


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

    async def refresh_sessions(self, sessions: list[dict]):
        lv = self.query_one("#session-list", ListView)
        await lv.clear()
        for s in sessions:
            await lv.append(SessionItem(s["id"], s.get("title", "Untitled")))

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

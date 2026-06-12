"""CliTer themes."""

THEMES = {
    "dark": {
        "background": "#1a1a2e",
        "surface": "#16213e",
        "primary": "#0f3460",
        "accent": "#e94560",
        "text": "#eee",
        "text_muted": "#888",
        "border": "#333",
        "success": "#00ff41",
        "error": "#ff4444",
        "user_msg": "#0f3460",
        "assistant_msg": "#1a1a2e",
    },
    "hacker": {
        "background": "#0a0a0a",
        "surface": "#111",
        "primary": "#003b00",
        "accent": "#00ff41",
        "text": "#00ff41",
        "text_muted": "#006400",
        "border": "#003b00",
        "success": "#00ff41",
        "error": "#ff0000",
        "user_msg": "#002200",
        "assistant_msg": "#0a0a0a",
    },
    "minimal": {
        "background": "#fafafa",
        "surface": "#fff",
        "primary": "#333",
        "accent": "#0066cc",
        "text": "#222",
        "text_muted": "#999",
        "border": "#ddd",
        "success": "#28a745",
        "error": "#dc3545",
        "user_msg": "#e8f4f8",
        "assistant_msg": "#fafafa",
    },
}

def get_theme(name: str = "dark") -> dict:
    return THEMES.get(name, THEMES["dark"])

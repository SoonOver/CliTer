"""Clipboard: termux-clipboard or xclip fallback."""
import subprocess, shutil
from cliter.utils.paths import is_termux

def copy(text: str):
    if is_termux():
        subprocess.run(["termux-clipboard-set"], input=text.encode(), check=False)
    elif shutil.which("xclip"):
        subprocess.run(["xclip", "-selection", "clipboard"], input=text.encode(), check=False)

def paste() -> str:
    try:
        if is_termux():
            r = subprocess.run(["termux-clipboard-get"], capture_output=True, text=True)
            return r.stdout
        elif shutil.which("xclip"):
            r = subprocess.run(["xclip", "-selection", "clipboard", "-o"], capture_output=True, text=True)
            return r.stdout
    except Exception:
        pass
    return ""

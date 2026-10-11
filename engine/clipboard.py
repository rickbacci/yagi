"""Read clipboard text without letting the owner stall the shell.

Qt 6.12 TextInput connects clipboard dataChanged to canPaste, and that
calls mimeData()->hasText(). On Wayland the read loops until the owner
closes the pipe, one second at a time, with no byte cap. The search
field stays read-only so Qt never does that. Paste comes through here:
a short deadline and a hard byte cap, and the text is never put on argv.
"""

import shutil
import subprocess

MAX_BYTES = 256
TIMEOUT_SEC = 0.2


def read_clipboard_text(max_bytes: int = MAX_BYTES, timeout: float = TIMEOUT_SEC) -> str:
    paste = shutil.which("wl-paste")
    if not paste:
        return ""
    argv = [paste, "--no-newline", "-t", "text/plain"]
    try:
        res = subprocess.run(argv, capture_output=True, timeout=timeout)
        data = res.stdout or b""
    except subprocess.TimeoutExpired as exc:
        data = exc.stdout or b""
    except OSError:
        return ""
    text = data[: max(0, int(max_bytes))].decode("utf-8", "ignore")
    return "".join(ch for ch in text if ch == "\t" or ord(ch) >= 32)

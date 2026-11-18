"""Read clipboard text without letting the owner stall the shell.

Qt 6.12 TextInput connects clipboard dataChanged to canPaste, and that
calls mimeData()->hasText(). On Wayland the read loops until the owner
closes the pipe, one second at a time, with no byte cap. The search
field stays read-only so Qt never does that. Paste comes through here:
a short deadline and a hard byte cap, and the text is never put on argv.
The cap is applied while the bytes are read, and the whole wl-paste
process group is stopped once the cap or the deadline is hit.

The only caller is guide search (plugin/GuidePage.qml searchLimit, and
bin/yagi clipboard-text). The field keeps 64 UTF-16 code units. The
largest UTF-8 encoding of one code unit is 3 bytes, so a full field is
192 bytes. 256 is the next round bound and leaves 64 bytes of headroom.
Nothing in Yagi pastes a URL, a path, or tuner data from the clipboard.
"""

import shutil
import subprocess

from engine.procio import capture

MAX_BYTES = 256
TIMEOUT_SEC = 0.2


def read_clipboard_text(max_bytes: int = MAX_BYTES, timeout: float = TIMEOUT_SEC) -> str:
    paste = shutil.which("wl-paste")
    if not paste:
        return ""
    argv = [paste, "--no-newline", "-t", "text/plain"]
    cap = max(0, int(max_bytes))
    try:
        res = capture(argv, max_bytes=cap, timeout=timeout)
        data = res.stdout or b""
    except subprocess.TimeoutExpired as exc:
        data = exc.stdout or b""
    except OSError:
        return ""
    text = data[:cap].decode("utf-8", "ignore")
    return "".join(ch for ch in text if ch == "\t" or ord(ch) >= 32)

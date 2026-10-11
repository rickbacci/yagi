"""Compile every plugin QML file with Qt, offscreen.

A static import list is not enough: 0.1.3 put Process and StdioCollector
in GuidePage.qml without importing Quickshell.Io, the suite stayed green,
and the bar failed to load. This test builds a stub of Quickshell and of
qs.Ui / qs.Commons, then asks qmltestrunner to compile BarWidget.qml and
every page. An unknown type is a failure.

The same loader is pointed at plugin/GuidePage.qml from commit 08ae869,
which has no Quickshell.Io import, and that compile must fail.
"""

import os
import re
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest

from tests.test_qml_items import _tokenize

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(PROJECT_ROOT, "plugin")
# Arch puts Qt 5's qmltestrunner on PATH (/usr/bin) and Qt 6's at this path.
QT6_QMLTESTRUNNER = "/usr/lib/qt6/bin/qmltestrunner"
_QT6_VERSION = re.compile(r"\bQt\s*6(\.|$)")
_QT5_VERSION = re.compile(r"\bQt\s*5(\.|$)")


class QmlRunnerError(RuntimeError):
    """No usable Qt 6 qmltestrunner. A Qt 5 one on PATH is not a substitute."""


def qml_child_env(base=None):
    """Offscreen, with the desktop theme and display variables removed.

    A user session often sets QT_QPA_PLATFORMTHEME=gtk3. Qt 5 then warns
    'cannot open display' and exits before it compiles anything.
    """
    env = dict(base if base is not None else os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    for key in ("QT_QPA_PLATFORMTHEME", "DISPLAY", "WAYLAND_DISPLAY", "QT_STYLE_OVERRIDE"):
        env.pop(key, None)
    return env


def _version_text(path):
    env = qml_child_env()
    chunks = []
    for flag in ("-v", "--version", "-version"):
        try:
            proc = subprocess.run(
                [path, flag],
                capture_output=True,
                text=True,
                timeout=8,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        chunks.append((proc.stdout or "") + "\n" + (proc.stderr or ""))
    return "\n".join(chunks)


def _same_file(left, right):
    try:
        return os.path.isfile(left) and os.path.isfile(right) and os.path.samefile(left, right)
    except OSError:
        return False


def _reports_qt6(path):
    """True when this qmltestrunner is Qt 6. Qt 5's -v text, qmake6, or ldd decides."""
    text = _version_text(path)
    saw6 = bool(_QT6_VERSION.search(text))
    saw5 = bool(_QT5_VERSION.search(text))
    if saw6 and not saw5:
        return True
    if saw5 and not saw6:
        return False
    for tool in ("qtpaths6", "qmake6"):
        exe = shutil.which(tool)
        if not exe:
            continue
        try:
            bins = subprocess.run(
                [exe, "-query", "QT_INSTALL_BINS"],
                capture_output=True, text=True, timeout=8,
            )
            ver = subprocess.run(
                [exe, "-query", "QT_VERSION"],
                capture_output=True, text=True, timeout=8,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if not (ver.stdout or "").strip().startswith("6"):
            continue
        bindir = (bins.stdout or "").strip()
        if bindir and _same_file(path, os.path.join(bindir, "qmltestrunner")):
            return True
    try:
        ldd = subprocess.run(["ldd", path], capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return False
    linked = (ldd.stdout or "") + (ldd.stderr or "")
    if "libQt6Core" in linked or "libQt6Test" in linked:
        return True
    if "libQt5Core" in linked or "libQt5Test" in linked:
        return False
    return False


def find_qt6_qmltestrunner(search_path=None, fixed_paths=None):
    """Qt 6 runner. A Qt 5 qmltestrunner earlier on PATH is ignored.

    Order: /usr/lib/qt6/bin/qmltestrunner, qmltestrunner6, qmltestrunner-qt6,
    then PATH's qmltestrunner only when that binary reports Qt 6.
    """
    if fixed_paths is None:
        fixed_paths = (QT6_QMLTESTRUNNER,)
    chosen = []
    for path in fixed_paths:
        if path and os.path.isfile(path) and os.access(path, os.X_OK) and path not in chosen:
            chosen.append(path)
    for name in ("qmltestrunner6", "qmltestrunner-qt6"):
        found = shutil.which(name, path=search_path)
        if found and found not in chosen:
            chosen.append(found)
    on_path = shutil.which("qmltestrunner", path=search_path)
    if on_path and on_path not in chosen:
        if _reports_qt6(on_path):
            chosen.append(on_path)
        elif not chosen:
            raise QmlRunnerError(
                f"{on_path} is Qt 5. The QML tests need Qt 6, "
                f"for example {QT6_QMLTESTRUNNER} from qt6-declarative."
            )
    if not chosen:
        raise QmlRunnerError(
            "No Qt 6 qmltestrunner found. Install qt6-declarative "
            "(Ubuntu: qt6-declarative-dev-tools; Arch: qt6-declarative)."
        )
    return chosen[0]

QTQUICK = {
    "Item", "Rectangle", "Text", "MouseArea", "Column", "Row", "Flickable",
    "Repeater", "Loader", "Image", "Timer", "Flow", "NumberAnimation",
    "HoverHandler", "Component", "ListView", "Grid", "TextInput", "TextEdit",
    "TextArea", "FocusScope",
}
OBJECT_TYPES = {"Process", "StdioCollector", "FileView", "IpcHandler"}
ITEM_PROPS = {
    "id", "x", "y", "z", "width", "height", "implicitWidth", "implicitHeight",
    "anchors", "opacity", "visible", "enabled", "clip", "rotation", "scale",
    "focus", "activeFocus", "parent", "children", "states", "transitions",
    "layer", "antialiasing", "state", "transform", "baselineOffset", "smooth",
}


def _runner_available():
    try:
        find_qt6_qmltestrunner()
    except QmlRunnerError:
        return False
    return True


def _members(plugin_dir):
    """Property names and signal names assigned on each custom type."""
    props = {}
    signals = {}
    for name in os.listdir(plugin_dir):
        if not name.endswith(".qml"):
            continue
        with open(os.path.join(plugin_dir, name), encoding="utf-8") as handle:
            tokens = list(_tokenize(handle.read()))
        stack = []
        i = 0
        n = len(tokens)
        while i < n:
            kind, value, _line = tokens[i]
            if kind == "ident" and i + 1 < n and tokens[i + 1][0] == "{":
                stack.append(value if value[:1].isupper() else None)
                i += 2
                continue
            if kind == "{":
                stack.append(None)
                i += 1
                continue
            if kind == "}":
                if stack:
                    stack.pop()
                i += 1
                continue
            parent = stack[-1] if stack else None
            preceded_by_dot = i > 0 and tokens[i - 1][0] == "dot"
            if (
                kind == "ident"
                and parent
                and parent not in QTQUICK
                and not preceded_by_dot
                and i + 1 < n
                and tokens[i + 1][0] == ":"
                and value not in ITEM_PROPS
            ):
                if len(value) > 2 and value.startswith("on") and value[2].isupper():
                    sig = value[2].lower() + value[3:]
                    signals.setdefault(parent, set()).add(sig)
                else:
                    props.setdefault(parent, set()).add(value)
            i += 1
    return props, signals


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


def write_stubs(root, plugin_dir):
    props, signals = _members(plugin_dir)
    methods = {
        "KeyboardPanel": ["fittedContentHeight", "fittedContentWidth"],
        "FileView": ["text", "reload"],
    }
    local = {name[:-4] for name in os.listdir(plugin_dir) if name.endswith(".qml")}
    skip = {"BarWidget", "MultiEffect"} | OBJECT_TYPES | local
    for type_name in set(props) | set(signals):
        if type_name in skip or type_name in QTQUICK:
            continue
        body = ["import QtQuick", "Item {"]
        body.append("  property font font")
        for prop in sorted(props.get(type_name, ()) - {"font"}):
            body.append(f"  property var {prop}")
        for sig in sorted(signals.get(type_name, ())):
            body.append(f"  signal {sig}(var arg)")
        for fn in methods.get(type_name, ()):
            body.append(f"  function {fn}() {{ return arguments.length ? arguments[0] : undefined }}")
        body.append("}")
        _write(os.path.join(root, "qs", "Ui", f"{type_name}.qml"), "\n".join(body) + "\n")

    ui_lines = ["module qs.Ui"]
    ui_dir = os.path.join(root, "qs", "Ui")
    if os.path.isdir(ui_dir):
        for name in sorted(os.listdir(ui_dir)):
            if name.endswith(".qml"):
                ui_lines.append(f"{name[:-4]} 1.0 {name}")
    _write(os.path.join(ui_dir, "qmldir"), "\n".join(ui_lines) + "\n")

    _write(os.path.join(root, "qs", "Commons", "Color.qml"), textwrap.dedent("""\
        pragma Singleton
        import QtQuick
        QtObject {
          property color accent: "#7aa2f7"
          property color urgent: "#f7768e"
          property color muted: "#888888"
          property color foreground: "#eeeeee"
          property QtObject popups: QtObject { property color background: "#111111" }
        }
    """))
    _write(os.path.join(root, "qs", "Commons", "Style.qml"), textwrap.dedent("""\
        pragma Singleton
        import QtQuick
        QtObject {
          property real gapsOut: 8
          property QtObject font: QtObject {
            property int body: 14
            property int heading: 16
            property int title: 18
            property int display: 28
          }
          property QtObject spacing: QtObject {
            property real labelGap: 4
            property real xs: 2
          }
          function space(n) { return n }
          function normalFillFor(a, b) { return a }
          function hoverFillFor(a, b) { return a }
          function selectedFillFor(a, b) { return a }
        }
    """))
    _write(os.path.join(root, "qs", "Commons", "Border.qml"), textwrap.dedent("""\
        pragma Singleton
        import QtQuick
        QtObject {
          function controlSpec(a, b, c) { return a }
        }
    """))
    _write(os.path.join(root, "qs", "Commons", "qmldir"), textwrap.dedent("""\
        module qs.Commons
        singleton Color 1.0 Color.qml
        singleton Style 1.0 Style.qml
        singleton Border 1.0 Border.qml
    """))

    _write(os.path.join(root, "Quickshell", "Quickshell.qml"), textwrap.dedent("""\
        pragma Singleton
        import QtQuick
        QtObject {
          function env(name) { return "" }
        }
    """))
    _write(os.path.join(root, "Quickshell", "BarWidget.qml"), textwrap.dedent("""\
        import QtQuick
        Item {
          property string moduleName
          property var bar: ({
            barForeground: "#eee",
            foreground: "#eee",
            fontFamily: "sans-serif",
            vertical: false
          })
        }
    """))
    _write(os.path.join(root, "Quickshell", "IpcHandler.qml"), textwrap.dedent("""\
        import QtQuick
        QtObject { property string target }
    """))
    _write(os.path.join(root, "Quickshell", "qmldir"), textwrap.dedent("""\
        module Quickshell
        singleton Quickshell 1.0 Quickshell.qml
        BarWidget 1.0 BarWidget.qml
        IpcHandler 1.0 IpcHandler.qml
    """))

    io = {
        "Process": "property var command\n  property bool running: false\n  property var stdout\n  signal started()\n  signal exited(var code)",
        "StdioCollector": "property bool waitForEnd: true\n  property string text: \"\"\n  signal streamFinished()",
        "FileView": "property string path\n  property bool watchChanges\n  property bool printErrors\n  signal loaded()\n  signal fileChanged()\n  function text() { return \"\" }\n  function reload() {}",
    }
    io_lines = ["module Quickshell.Io"]
    for name, body in io.items():
        _write(os.path.join(root, "Quickshell", "Io", f"{name}.qml"), f"import QtQuick\nQtObject {{\n  {body}\n}}\n")
        io_lines.append(f"{name} 1.0 {name}.qml")
    _write(os.path.join(root, "Quickshell", "Io", "qmldir"), "\n".join(io_lines) + "\n")

    _write(os.path.join(root, "QtQuick", "Effects", "MultiEffect.qml"), textwrap.dedent("""\
        import QtQuick
        Item {
          property var source
          property real colorization
          property color colorizationColor
        }
    """))
    _write(os.path.join(root, "QtQuick", "Effects", "qmldir"), "module QtQuick.Effects\nMultiEffect 1.0 MultiEffect.qml\n")


def _harness(qml_file, create):
    create_block = ""
    if create:
        create_block = textwrap.dedent("""\
            var object = component.createObject(null)
            verify(object !== null)
            object.destroy()
        """)
    return textwrap.dedent(f"""\
        import QtQuick
        import QtTest
        TestCase {{
          name: "load"
          function test_compile_and_create() {{
            var component = Qt.createComponent({qml_file!r})
            if (component.status !== Component.Ready)
              console.log("LOAD_ERROR " + component.errorString())
            compare(component.status, Component.Ready)
            {create_block}
          }}
        }}
    """)


def compile_qml(qml_file, import_root, plugin_dir, create=False):
    """Return (ok, output). Compiles and instantiates qml_file."""
    try:
        runner = find_qt6_qmltestrunner()
    except QmlRunnerError as exc:
        return False, str(exc)
    work = tempfile.mkdtemp(prefix="qml-load-")
    try:
        os.chmod(work, 0o700)
        harness = os.path.join(work, "tst_Load.qml")
        with open(harness, "w", encoding="utf-8") as handle:
            handle.write(_harness(os.path.abspath(qml_file), create))
        env = qml_child_env()
        env["XDG_RUNTIME_DIR"] = work
        env["QML2_IMPORT_PATH"] = import_root
        env["QML_IMPORT_PATH"] = import_root
        proc = subprocess.run(
            [runner, "-input", harness, "-o", "-,txt", "-import", import_root],
            capture_output=True,
            text=True,
            env=env,
            cwd=plugin_dir,
            timeout=60,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0 and "FAIL!" not in output, output
    finally:
        shutil.rmtree(work, ignore_errors=True)


class TestQmlLoads(unittest.TestCase):
    def setUp(self):
        try:
            find_qt6_qmltestrunner()
        except QmlRunnerError as exc:
            self.fail(str(exc))

    def test_a_qt5_runner_earlier_on_path_is_not_used(self):
        with tempfile.TemporaryDirectory() as folder:
            fake = os.path.join(folder, "qmltestrunner")
            with open(fake, "w", encoding="utf-8") as handle:
                handle.write(
                    "#!/bin/sh\n"
                    "case \"$1\" in\n"
                    "-v|--version|-version)\n"
                    "  echo 'qmltestrunner version 5.15.16'\n"
                    "  echo 'Qt 5.15.16'\n"
                    "  exit 0\n"
                    "  ;;\n"
                    "esac\n"
                    "echo 'Gtk-WARNING cannot open display' >&2\n"
                    "exit 1\n"
                )
            os.chmod(fake, stat.S_IRWXU)
            search = folder + os.pathsep + os.environ.get("PATH", "")
            self.assertEqual(shutil.which("qmltestrunner", path=search), fake)
            chosen = find_qt6_qmltestrunner(search)
        self.assertFalse(_same_file(chosen, fake))
        self.assertTrue(
            chosen == QT6_QMLTESTRUNNER or _reports_qt6(chosen),
            chosen,
        )

    def test_only_a_qt5_runner_fails_with_a_clear_message(self):
        with tempfile.TemporaryDirectory() as folder:
            fake = os.path.join(folder, "qmltestrunner")
            with open(fake, "w", encoding="utf-8") as handle:
                handle.write("#!/bin/sh\necho 'Qt 5.15.16'\nexit 0\n")
            os.chmod(fake, stat.S_IRWXU)
            with self.assertRaises(QmlRunnerError) as caught:
                find_qt6_qmltestrunner(folder, fixed_paths=())
        self.assertIn("Qt 5", str(caught.exception))
        self.assertIn(fake, str(caught.exception))

    def test_bar_widget_compiles_and_instantiates(self):
        with tempfile.TemporaryDirectory() as stubs:
            write_stubs(stubs, PLUGIN)
            ok, output = compile_qml(
                os.path.join(PLUGIN, "BarWidget.qml"), stubs, PLUGIN, create=True,
            )
        self.assertTrue(ok, output)

    def test_every_plugin_page_compiles(self):
        with tempfile.TemporaryDirectory() as stubs:
            write_stubs(stubs, PLUGIN)
            failed = []
            for name in sorted(os.listdir(PLUGIN)):
                if not name.endswith(".qml"):
                    continue
                path = os.path.join(PLUGIN, name)
                ok, output = compile_qml(path, stubs, PLUGIN)
                if not ok:
                    failed.append(name + "\n" + output)
        self.assertEqual(failed, [])

    def test_release_08ae869_guide_page_is_not_a_type(self):
        """plugin/GuidePage.qml at 08ae869 used StdioCollector without importing it."""
        fixture = os.path.join(PROJECT_ROOT, "tests", "fixtures", "GuidePage-08ae869.qml")
        with open(fixture, encoding="utf-8") as handle:
            broken_src = handle.read()
        self.assertNotIn("import Quickshell.Io", broken_src)
        self.assertIn("StdioCollector", broken_src)
        with tempfile.TemporaryDirectory() as tree:
            plugin = os.path.join(tree, "plugin")
            shutil.copytree(PLUGIN, plugin, ignore=shutil.ignore_patterns("__pycache__"))
            broken = os.path.join(plugin, "GuidePage.qml")
            with open(broken, "w", encoding="utf-8") as handle:
                handle.write(broken_src)
            os.chmod(broken, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
            stubs = os.path.join(tree, "stubs")
            write_stubs(stubs, plugin)
            ok, output = compile_qml(
                os.path.join(plugin, "BarWidget.qml"), stubs, plugin, create=True,
            )
        self.assertFalse(ok, output)
        self.assertTrue(
            "StdioCollector" in output or "Process is not a type" in output,
            output,
        )
        self.assertTrue("not a type" in output or "unavailable" in output, output)


if __name__ == "__main__":
    unittest.main()

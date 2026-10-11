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
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest

from tests.test_qml_items import _tokenize

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(PROJECT_ROOT, "plugin")
QML_RUNNER = (
    shutil.which("qmltestrunner")
    or ("/usr/lib/qt6/bin/qmltestrunner" if os.path.isfile("/usr/lib/qt6/bin/qmltestrunner") else "")
)

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
    return bool(QML_RUNNER) and os.path.isfile(QML_RUNNER)


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
    if not _runner_available():
        return False, "qmltestrunner is not installed"
    work = tempfile.mkdtemp(prefix="qml-load-")
    try:
        os.chmod(work, 0o700)
        harness = os.path.join(work, "tst_Load.qml")
        with open(harness, "w", encoding="utf-8") as handle:
            handle.write(_harness(os.path.abspath(qml_file), create))
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["XDG_RUNTIME_DIR"] = work
        env["QML2_IMPORT_PATH"] = import_root
        env["QML_IMPORT_PATH"] = import_root
        proc = subprocess.run(
            [QML_RUNNER, "-input", harness, "-o", "-,txt", "-import", import_root],
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
        if not _runner_available():
            self.fail("qmltestrunner is required; run scripts/setup-test-env.sh")

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
        """The merged 0.1.3 file used StdioCollector without importing it."""
        show = subprocess.run(
            ["git", "show", "08ae869:plugin/GuidePage.qml"],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        if show.returncode != 0:
            fetched = subprocess.run(
                ["git", "fetch", "--depth", "1", "origin", "08ae869"],
                capture_output=True,
                text=True,
                cwd=PROJECT_ROOT,
            )
            show = subprocess.run(
                ["git", "show", "08ae869:plugin/GuidePage.qml"],
                capture_output=True,
                text=True,
                cwd=PROJECT_ROOT,
            )
            self.assertEqual(show.returncode, 0, (show.stderr or "") + (fetched.stderr or ""))
        self.assertNotIn("import Quickshell.Io", show.stdout)
        with tempfile.TemporaryDirectory() as tree:
            plugin = os.path.join(tree, "plugin")
            shutil.copytree(PLUGIN, plugin, ignore=shutil.ignore_patterns("__pycache__"))
            broken = os.path.join(plugin, "GuidePage.qml")
            with open(broken, "w", encoding="utf-8") as handle:
                handle.write(show.stdout)
            os.chmod(broken, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
            stubs = os.path.join(tree, "stubs")
            write_stubs(stubs, plugin)
            ok, output = compile_qml(
                os.path.join(plugin, "BarWidget.qml"), stubs, plugin, create=True,
            )
        self.assertFalse(ok, output)
        self.assertIn("StdioCollector", output)
        self.assertTrue("not a type" in output or "unavailable" in output)


if __name__ == "__main__":
    unittest.main()

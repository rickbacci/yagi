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
import sys
import tempfile
import textwrap
import unittest

from tests.test_qml_items import _tokenize

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(PROJECT_ROOT, "plugin")
STUBS = os.path.join(PROJECT_ROOT, "tests", "qmlstub")
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
                f"{on_path} is Qt 5. The QML tests need a Qt 6 qmltestrunner "
                f"from qt6-declarative / qt6-declarative-dev-tools "
                f"(for example {QT6_QMLTESTRUNNER})."
            )
    if not chosen:
        raise QmlRunnerError(
            "No Qt 6 qmltestrunner found. Install qt6-declarative / "
            "qt6-declarative-dev-tools."
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


def _required_props(text):
    found = []
    for line in text.splitlines():
        match = re.match(r"  required property (\S+) (\w+)\s*$", line)
        if match:
            found.append((match.group(2), match.group(1)))
    return found


def _harness(qml_file, create, required, bind_required=True):
    create_block = ""
    if create and not bind_required:
        create_block = "\n".join([
            "var object = component.createObject(null, {})",
            "if (object !== null) object.destroy()",
            "verify(object === null)",
        ])
    elif create:
        assigns = []
        for name, typ in required:
            if name == "tv":
                assigns.append("props.tv = tv")
            elif typ == "Item":
                assigns.append(f"props.{name} = host")
            elif typ in ("int", "real"):
                assigns.append(f"props.{name} = 0")
            elif typ == "string":
                assigns.append(f"props.{name} = ''")
            elif typ == "bool":
                assigns.append(f"props.{name} = false")
            else:
                assigns.append(f"props.{name} = ({{}})")
        needs_host = any(typ == "Item" and name != "tv" for name, typ in required)
        create_block = "\n".join([
            "var host = Qt.createQmlObject('import QtQuick; Item {}', this)" if needs_host else "var host = null",
            "var tv = {",
            "  bar: {foreground: '#eee', fontFamily: 'sans-serif', vertical: false, barForeground: '#eee'},",
            "  guideStripOpen: false, guideTab: 'grid', guideSearchText: '', guideSearchActive: false,",
            "  gridRows: [], displayChannels: [], channelsData: [], guideShowRows: [],",
            "  activeChannelName: '', isScanning: false, tuning: false, libraryTab: 'recorded',",
            "  libraryShow: '', recordedPicks: [], scheduledPicks: [], scheduledRows: [],",
            "  binPath: 'yagi', channelFilter: 'all', guideClockMin: 0, showBucket: 'day',",
            "  cursorActive: false, libraryModalOpen: false, gridNow: 0, gridMatchCount: 0,",
            "  favoriteVisibleCount: 0, watchableChannels: [], showsLoading: false, scanSignal: null,",
            "  guideRefreshing: false, guideWaitReason: '', guideStatusError: '',",
            "  guideStatusTowers: 0, guideStatusTower: 0, scheduleLine: '',",
            "  tunePhase: '', tuneMessage: '', tuneDisplay: '', tuneName: '', tuneSnr: '',",
            "  pendingWatch: '', ruleIds: {},",
            "  getActiveProgram: function() { return null },",
            "  getProgram: function() { return null },",
            "  getActiveDisplayName: function() { return '' },",
            "  stationFor: function() { return '' },",
            "  roomFor: function() { return 100 },",
            "  guideListRoom: function() { return 100 },",
            "  hitRecordState: function() { return '' },",
            "  hitRuleId: function() { return '' },",
            "  isChannelRecording: function() { return false },",
            "  channelIsFavorite: function() { return false },",
            "  channelIsHidden: function() { return false }",
            "}",
            "var props = {}",
            *assigns,
            "var object = component.createObject(null, props)",
            "if (object === null) console.log('CREATE_FAIL ' + component.errorString())",
            "verify(object !== null)",
            "object.destroy()",
        ])
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


_ANNOUNCED = False


def _qt_label(path):
    text = _version_text(path)
    match = re.search(r"Qt(?:Test library)?\s*([0-9]+\.[0-9]+\.[0-9]+)", text)
    if match:
        return "Qt " + match.group(1)
    try:
        ldd = subprocess.run(["ldd", path], capture_output=True, text=True, timeout=8)
        linked = ldd.stdout or ""
        lib = re.search(r"(libQt6Core\.so[^ ]*)", linked)
        if lib:
            target = os.path.realpath(lib.group(1)) if os.path.isabs(lib.group(1)) else ""
            # ldd prints "libQt6Core.so.6 => /path/libQt6Core.so.6.4.2"
            resolved = re.search(r"libQt6Core\.so\.6\s*=>\s*(\S+)", linked)
            if resolved:
                real = os.path.realpath(resolved.group(1))
                ver = re.search(r"\.so\.6\.([0-9.]+)", os.path.basename(real))
                if ver:
                    return "Qt 6." + ver.group(1)
            return "Qt 6"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "Qt 6"


def _announce(path):
    global _ANNOUNCED
    if _ANNOUNCED:
        return
    _ANNOUNCED = True
    print(f"qmltestrunner {path} ({_qt_label(path)})", file=sys.stderr)


_LOAD_FAILURES = (
    "QWARN",
    "Cannot assign",
    "is not a type",
    "non-existent property",
    "ReferenceError",
    "TypeError",
    "Required property",
    "Script exception",
)


_CHECKED_SINGLETONS = {"Color", "Style", "Border", "Quickshell"}
_STUB_MEMBERS = None


def stub_members():
    """property and function names on the checked-in stubs, with nested types."""
    global _STUB_MEMBERS
    if _STUB_MEMBERS is not None:
        return _STUB_MEMBERS
    found = {}
    for dirpath, _dirs, names in os.walk(STUBS):
        for name in names:
            if not name.endswith(".qml"):
                continue
            with open(os.path.join(dirpath, name), encoding="utf-8") as handle:
                text = handle.read()
            props = {}
            for match in re.finditer(r"property\s+(\w+)\s+(\w+)", text):
                props[match.group(2)] = match.group(1)
            for match in re.finditer(r"function\s+(\w+)\s*\(", text):
                props[match.group(1)] = ""
            found[name[:-4]] = props
    _STUB_MEMBERS = found
    return found


def singleton_member_problems(text):
    """Color.accent is checked against the stub. Qt 6.4 reads a missing one as undefined."""
    tokens = list(_tokenize(text))
    members = stub_members()
    problems = []
    for i, (kind, value, line) in enumerate(tokens):
        if kind != "ident" or value not in _CHECKED_SINGLETONS:
            continue
        if i + 2 >= len(tokens) or tokens[i + 1][0] != "dot" or tokens[i + 2][0] != "ident":
            continue
        if i > 0 and (tokens[i - 1][0] == "dot" or tokens[i - 1][1] == "import"):
            continue
        owner = value
        j = i + 2
        while True:
            member = tokens[j][1]
            declared = members.get(owner, {})
            if member not in declared:
                problems.append(f"{line}: {owner}.{member} is not a member of the stub")
                break
            nxt = j + 2
            if nxt < len(tokens) and tokens[j + 1][0] == "dot" and tokens[nxt][0] == "ident":
                nested = declared[member]
                if nested not in members:
                    problems.append(f"{line}: {owner}.{member} has no nested members on the stub")
                    break
                owner = nested
                j = nxt
                continue
            break
    return problems


def compile_qml(qml_file, import_root, plugin_dir, create=False, bind_required=True):
    """Return (ok, output). Compiles and instantiates qml_file."""
    with open(qml_file, encoding="utf-8") as handle:
        source = handle.read()
    missing = singleton_member_problems(source)
    if missing:
        return False, "\n".join(missing)
    try:
        runner = find_qt6_qmltestrunner()
    except QmlRunnerError as exc:
        return False, str(exc)
    _announce(runner)
    required = []
    if create:
        with open(qml_file, encoding="utf-8") as handle:
            required = _required_props(handle.read())
    work = tempfile.mkdtemp(prefix="qml-load-")
    try:
        os.chmod(work, 0o700)
        harness = os.path.join(work, "tst_Load.qml")
        with open(harness, "w", encoding="utf-8") as handle:
            handle.write(_harness(os.path.abspath(qml_file), create, required, bind_required))
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
        warned = any(token in output for token in _LOAD_FAILURES)
        return proc.returncode == 0 and "FAIL!" not in output and not warned, output
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
        message = str(caught.exception)
        self.assertIn("Qt 5", message)
        self.assertIn(fake, message)
        self.assertIn("qt6-declarative", message)
        self.assertIn("qt6-declarative-dev-tools", message)

    def test_a_missing_runner_names_both_packages(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(QmlRunnerError) as caught:
                find_qt6_qmltestrunner(folder, fixed_paths=())
        message = str(caught.exception)
        self.assertIn("qt6-declarative", message)
        self.assertIn("qt6-declarative-dev-tools", message)

    def test_the_runner_reports_qt6(self):
        label = _qt_label(find_qt6_qmltestrunner())
        self.assertRegex(label, r"^Qt 6\.\d+")
        _announce(find_qt6_qmltestrunner())

    def test_bar_widget_compiles_and_instantiates(self):
        ok, output = compile_qml(
            os.path.join(PLUGIN, "BarWidget.qml"), STUBS, PLUGIN, create=True,
        )
        self.assertTrue(ok, output)
        self.assertNotIn("QWARN", output)
        self.assertNotIn("Cannot assign", output)

    def test_release_0_1_1_bar_rejects_a_hover_handler_in_the_panel(self):
        """0.1.1 put HoverHandler directly in KeyboardPanel, which only accepts items."""
        fixture = os.path.join(PROJECT_ROOT, "tests", "fixtures", "BarWidget-0.1.1.qml")
        with open(fixture, encoding="utf-8") as handle:
            broken_src = handle.read()
        self.assertIn("HoverHandler", broken_src)
        with tempfile.TemporaryDirectory() as tree:
            plugin = os.path.join(tree, "plugin")
            shutil.copytree(PLUGIN, plugin, ignore=shutil.ignore_patterns("__pycache__"))
            target = os.path.join(plugin, "BarWidget.qml")
            with open(target, "w", encoding="utf-8") as handle:
                handle.write(broken_src)
            ok, output = compile_qml(target, STUBS, plugin, create=True)
        self.assertFalse(ok, output)
        self.assertIn("contentItem", output)
        self.assertIn("Cannot assign", output)

    def test_every_plugin_page_compiles(self):
        failed = []
        for name in sorted(os.listdir(PLUGIN)):
            if not name.endswith(".qml"):
                continue
            path = os.path.join(PLUGIN, name)
            ok, output = compile_qml(path, STUBS, PLUGIN, create=True)
            if not ok or "QWARN" in output or "Cannot assign" in output:
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
            ok, output = compile_qml(
                os.path.join(plugin, "BarWidget.qml"), STUBS, plugin, create=True,
            )
        self.assertFalse(ok, output)
        self.assertTrue(
            "StdioCollector" in output or "Process is not a type" in output,
            output,
        )
        self.assertTrue("not a type" in output or "unavailable" in output, output)

    def _snippet(self, name, src, create=True, bind_required=True):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, name)
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(src)
            return compile_qml(path, STUBS, folder, create=create, bind_required=bind_required)

    def test_an_unknown_property_fails_the_load(self):
        ok, output = self._snippet("bad.qml", textwrap.dedent("""\
            import QtQuick
            import qs.Ui
            Item {
              KeyboardPanel {
                anchorItem: parent
                bar: ({})
                notARealProperty: 1
              }
            }
        """))
        self.assertFalse(ok, output)
        self.assertIn("notARealProperty", output)

    def test_a_missing_singleton_member_fails_the_load(self):
        ok, output = self._snippet("bad.qml", textwrap.dedent("""\
            import QtQuick
            import qs.Commons
            Item {
              property color c: Color.noSuchMember
            }
        """))
        self.assertFalse(ok, output)
        self.assertTrue(
            "noSuchMember" in output or "non-existent property" in output,
            output,
        )

    def test_a_page_missing_its_required_property_does_not_instantiate(self):
        src = "import QtQuick\nItem {\n  required property var tv\n}\n"
        ok, output = self._snippet("need.qml", src, bind_required=False)
        self.assertFalse(ok, output)
        self.assertIn("Required property", output)
        ok, output = self._snippet("need.qml", src, bind_required=True)
        self.assertTrue(ok, output)

    def test_a_page_that_throws_on_create_fails(self):
        ok, output = self._snippet("boom.qml", textwrap.dedent("""\
            import QtQuick
            Item {
              Component.onCompleted: notAFunction()
            }
        """))
        self.assertFalse(ok, output)


if __name__ == "__main__":
    unittest.main()

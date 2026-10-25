"""Plugin QML must not put a non-item in an item-only default property.

KeyboardPanel's default property is contentItem, a list of QQuickItem.
A HoverHandler there is how 0.1.1 failed to load the bar:

    Cannot assign object of type "QQuickHoverHandler" to list property
    "contentItem"; expected "QQuickItem"

qmllint is not used: it cannot see the Quickshell modules that define
KeyboardPanel. This walks every plugin QML file instead.
"""

import os
import re
import unittest


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN = os.path.join(PROJECT_ROOT, "plugin")

# Default property is a list of items, not Item.data (which also takes resources).
ITEM_ONLY_PARENTS = {"KeyboardPanel"}

# Not QQuickItem. A direct child of an item-only parent will not load.
NON_ITEMS = {
    "HoverHandler",
    "TapHandler",
    "DragHandler",
    "WheelHandler",
    "PinchHandler",
    "PointHandler",
    "Timer",
    "Connections",
    "Binding",
    "QtObject",
    "Component",
    "Behavior",
    "State",
    "Transition",
    "NumberAnimation",
    "PropertyAnimation",
    "SequentialAnimation",
    "ParallelAnimation",
    "PauseAnimation",
    "ColorAnimation",
    "SmoothedAnimation",
    "SpringAnimation",
    "OpacityAnimator",
    "RotationAnimator",
    "ScaleAnimator",
    "XAnimator",
    "YAnimator",
    "ScriptAction",
    "PropertyAction",
}


def _is_non_item(type_name):
    return type_name in NON_ITEMS or type_name.endswith("Handler")


def _tokenize(text):
    """Identifiers, braces, and colons. Strings and comments are skipped."""
    i = 0
    n = len(text)
    line = 1
    while i < n:
        ch = text[i]
        if ch == "\n":
            line += 1
            i += 1
            continue
        if ch in " \t\r":
            i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            i += 2
            while i < n and text[i] != "\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                if text[i] == "\n":
                    line += 1
                i += 1
            i = min(n, i + 2)
            continue
        if ch in "\"'":
            quote = ch
            i += 1
            while i < n and text[i] != quote:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == "\n":
                    line += 1
                i += 1
            i = min(n, i + 1)
            continue
        if ch.isalpha() or ch == "_":
            start = i
            i += 1
            while i < n and (text[i].isalnum() or text[i] == "_"):
                i += 1
            yield ("ident", text[start:i], line)
            continue
        if ch in "{}:":
            yield (ch, ch, line)
            i += 1
            continue
        if ch == ".":
            yield ("dot", ".", line)
            i += 1
            continue
        if ch in "()":
            yield (ch, ch, line)
            i += 1
            continue
        i += 1


def item_only_problems(text, path=""):
    """Default-property children that are not items, under an item-only parent."""
    problems = []
    stack = [None]
    pending = None
    # `name: Type {}` is a property value, not a default-property child.
    awaiting_value = False
    for kind, value, line in _tokenize(text):
        if kind == "ident":
            pending = (value, line)
            continue
        if kind == "{":
            type_name, type_line = pending if pending else (None, line)
            is_value = awaiting_value
            pending = None
            awaiting_value = False
            parent = stack[-1]
            if type_name and type_name[0].isupper():
                if not is_value and parent in ITEM_ONLY_PARENTS and _is_non_item(type_name):
                    where = f"{path}:{type_line}" if path else str(type_line)
                    problems.append(
                        f"{where}: {type_name} is not an item, and {parent} only accepts items"
                    )
                stack.append(type_name)
            else:
                stack.append(None)
            continue
        if kind == ":":
            pending = None
            awaiting_value = True
            continue
        if kind == "}":
            pending = None
            awaiting_value = False
            if len(stack) > 1:
                stack.pop()
            continue
        if kind == "dot":
            continue
        if kind in ("(", ")"):
            pending = None
            awaiting_value = False
            continue
        pending = None
        awaiting_value = False
    return problems


# Qt Quick editable controls. A live one, even read-only until the first
# key, is still a TextInput once readOnly is false. These must not be
# created until a Loader with active false (or a bool that starts false)
# turns on.
EDITABLE_INPUTS = {"TextField", "TextInput", "TextEdit", "TextArea"}


def _is_property(tokens, index):
    """True when tokens[index] begins `name` or `name.member` and then a colon."""
    if index >= len(tokens) or tokens[index][0] != "ident":
        return False
    j = index + 1
    while j + 1 < len(tokens) and tokens[j][0] == "dot" and tokens[j + 1][0] == "ident":
        j += 2
    return j < len(tokens) and tokens[j][0] == ":"


def _binding_starts_false(parts, false_bools):
    if parts == ["false"]:
        return True
    if len(parts) == 1 and parts[0] in false_bools:
        return True
    if len(parts) == 2 and parts[1] in false_bools:
        return True
    return False


def editable_input_problems(text, path=""):
    """Editable fields must sit in a Loader that is inactive by default.

    `active` has to appear before the field in the file so the check can
    see it. `property bool name: false` counts as inactive when `active`
    is `name` or `id.name`.
    """
    false_bools = set(re.findall(r"property\s+bool\s+(\w+)\s*:\s*false\b", text))
    tokens = list(_tokenize(text))
    problems = []
    stack = [{"type": None, "inactive": False}]
    i = 0
    n = len(tokens)
    while i < n:
        kind, value, line = tokens[i]
        if kind == "ident" and i + 1 < n and tokens[i + 1][0] == "{":
            type_name = value if value[:1].isupper() else None
            if type_name in EDITABLE_INPUTS:
                if not any(frame["type"] == "Loader" and frame["inactive"] for frame in stack):
                    where = f"{path}:{line}" if path else str(line)
                    problems.append(
                        f"{where}: {type_name} is editable and is not inside a Loader that is inactive by default"
                    )
            stack.append({"type": type_name, "inactive": False})
            i += 2
            continue
        if kind == "{":
            stack.append({"type": None, "inactive": False})
            i += 1
            continue
        if kind == "}":
            if len(stack) > 1:
                stack.pop()
            i += 1
            continue
        if (
            kind == "ident"
            and value == "active"
            and stack[-1]["type"] == "Loader"
            and i + 1 < n
            and tokens[i + 1][0] == ":"
        ):
            i += 2
            parts = []
            while i < n and tokens[i][0] == "ident":
                if parts and _is_property(tokens, i):
                    break
                if i + 1 < n and tokens[i + 1][0] == "{":
                    break
                parts.append(tokens[i][1])
                i += 1
                if i < n and tokens[i][0] == "dot":
                    i += 1
                    continue
                break
            stack[-1]["inactive"] = _binding_starts_false(parts, false_bools)
            continue
        i += 1
    return problems


# Types a file may use only when it imports the module that provides them.
# Sibling .qml files in plugin/ are available without an import.
MODULE_TYPES = {
    "QtQuick": {
        "Item", "Rectangle", "Text", "MouseArea", "Column", "Row", "Flickable",
        "Repeater", "Loader", "Image", "Timer", "Flow", "NumberAnimation",
        "HoverHandler", "Component", "ListView", "Grid", "TextInput", "TextEdit",
        "TextArea", "ShaderEffect", "Canvas", "FocusScope", "AnimatedImage",
    },
    "QtQuick.Controls": {"TextField", "Button", "ScrollBar", "ComboBox", "Slider", "Label", "Popup", "Pane"},
    "QtQuick.Effects": {"MultiEffect"},
    "QtQuick.Layouts": {"ColumnLayout", "RowLayout", "GridLayout", "StackLayout"},
    "QtQuick.Window": {"Window"},
    "Quickshell": {"BarWidget", "IpcHandler", "PanelWindow", "Scope", "Variants"},
    "Quickshell.Io": {"Process", "StdioCollector", "FileView", "SplitParser", "Socket"},
    "Quickshell.Wayland": {"WlrLayershell"},
    "qs.Ui": {
        "Button", "CursorSurface", "KeyboardPanel", "PanelKeyCatcher",
        "BorderSurface", "PanelActionButton", "PanelToolTip", "TextField",
    },
    "qs.Commons": set(),
}


def _imports(text):
    found = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("import ") or stripped.startswith("import \""):
            continue
        parts = stripped.split()
        if len(parts) >= 2:
            found.append(parts[1])
    return found


def _used_types(text):
    types = []
    tokens = list(_tokenize(text))
    for i, (kind, value, line) in enumerate(tokens):
        if kind == "ident" and value[:1].isupper() and i + 1 < len(tokens) and tokens[i + 1][0] == "{":
            types.append((value, line))
    return types


# Uppercase name before a dot. Qt and Easing come with QtQuick. Screen is QtQuick.Window.
SINGLETON_IMPORT = {
    "Color": "qs.Commons",
    "Style": "qs.Commons",
    "Border": "qs.Commons",
    "Quickshell": "Quickshell",
    "Screen": "QtQuick.Window",
    "Qt": "QtQuick",
    "Easing": "QtQuick",
    "Keys": "QtQuick",
    "Component": "QtQuick",
    "Text": "QtQuick",
}


def _singleton_uses(text):
    tokens = list(_tokenize(text))
    uses = []
    for i, (kind, value, line) in enumerate(tokens):
        if kind != "ident" or not value[:1].isupper():
            continue
        if i + 1 >= len(tokens) or tokens[i + 1][0] != "dot":
            continue
        if i > 0 and tokens[i - 1][0] == "dot":
            # C.Color.accent is still the qs.Commons palette. The qualifier
            # is required on Qt 6.12, where unqualified Color is QtQuick's.
            if value == "Color" and i >= 2 and tokens[i - 2][0] == "ident":
                uses.append((value, line))
            continue
        if i > 0 and tokens[i - 1] == ("ident", "import", tokens[i - 1][2]):
            continue
        uses.append((value, line))
    return uses


def missing_import_problems(text, path, sibling_types):
    """A type or singleton used here must come from an import or a sibling file."""
    imported = set(_imports(text))
    aliases = set(re.findall(r'import\s+"[^"]+"\s+as\s+(\w+)', text))
    provided = set(sibling_types)
    provided.update(re.findall(r"\bcomponent\s+([A-Z]\w*)", text))
    for name in imported:
        if name not in MODULE_TYPES:
            continue
        provided.update(MODULE_TYPES[name])
    problems = []
    for type_name, line in _used_types(text):
        if type_name in provided:
            continue
        where = f"{path}:{line}" if path else str(line)
        problems.append(f"{where}: {type_name} is used but no import in this file provides it")
    for name, line in _singleton_uses(text):
        if name in aliases or name in sibling_types:
            continue
        need = SINGLETON_IMPORT.get(name)
        if need is None or need in imported:
            continue
        where = f"{path}:{line}" if path else str(line)
        problems.append(f"{where}: {name} needs `import {need}`")
    return problems


class TestQmlItems(unittest.TestCase):
    def test_hover_handler_directly_in_keyboard_panel_is_rejected(self):
        src = "KeyboardPanel {\n  HoverHandler {}\n  Item {}\n}\n"
        found = item_only_problems(src)
        self.assertEqual(len(found), 1)
        self.assertIn("HoverHandler", found[0])
        self.assertIn("KeyboardPanel", found[0])

    def test_hover_handler_inside_an_item_is_allowed(self):
        src = "KeyboardPanel {\n  PanelKeyCatcher {\n    anchors.fill: parent\n    HoverHandler {}\n  }\n}\n"
        self.assertEqual(item_only_problems(src), [])

    def test_a_handler_assigned_to_a_property_is_not_a_default_child(self):
        src = "KeyboardPanel {\n  contentData: HoverHandler {}\n}\n"
        self.assertEqual(item_only_problems(src), [])

    def test_plugin_qml_puts_no_non_item_in_an_item_only_parent(self):
        found = []
        for name in sorted(os.listdir(PLUGIN)):
            if not name.endswith(".qml"):
                continue
            path = os.path.join(PLUGIN, name)
            with open(path, encoding="utf-8") as handle:
                found.extend(item_only_problems(handle.read(), path))
        self.assertEqual(found, [])

    def test_a_bare_text_field_is_rejected(self):
        src = "Item {\n  TextField { text: \"hi\" }\n}\n"
        found = editable_input_problems(src)
        self.assertEqual(len(found), 1)
        self.assertIn("TextField", found[0])

    def test_a_loader_that_starts_active_is_rejected(self):
        src = "Loader {\n  active: true\n  sourceComponent: Component {\n    TextInput {}\n  }\n}\n"
        self.assertTrue(editable_input_problems(src))

    def test_a_loader_inactive_by_default_may_hold_a_field(self):
        src = (
            "Loader {\n  active: false\n  sourceComponent: Component {\n    TextEdit {}\n  }\n}\n"
        )
        self.assertEqual(editable_input_problems(src), [])

    def test_a_bool_that_starts_false_keeps_the_loader_inactive(self):
        src = (
            "Item {\n  property bool searchOpen: false\n"
            "  Loader {\n    active: guide.searchOpen\n"
            "    sourceComponent: Component { TextField { readOnly: true } }\n  }\n}\n"
        )
        self.assertEqual(editable_input_problems(src), [])
        missing = "Loader {\n  active: guide.searchOpen\n  TextArea {}\n}\n"
        self.assertTrue(editable_input_problems(missing))

    def test_color_without_commons_import_is_rejected(self):
        src = "import QtQuick\nItem { color: Color.accent }\n"
        found = missing_import_problems(src, "", set())
        self.assertTrue(any("Color" in item and "qs.Commons" in item for item in found))
        src = "import QtQuick\nimport qs.Commons\nItem { color: Color.accent }\n"
        self.assertEqual(missing_import_problems(src, "", set()), [])
        for name, need, use in (
            ("Style", "qs.Commons", "Style.gapsOut"),
            ("Border", "qs.Commons", "Border.controlSpec"),
            ("Quickshell", "Quickshell", "Quickshell.env"),
        ):
            bare = f"import QtQuick\nItem {{ property var x: {use} }}\n"
            found = missing_import_problems(bare, "", set())
            self.assertTrue(any(name in item and need in item for item in found), found)
            imported = f"import QtQuick\nimport {need}\nItem {{ property var x: {use} }}\n"
            self.assertEqual(missing_import_problems(imported, "", set()), [])

    def test_a_type_without_its_import_is_rejected(self):
        src = "import QtQuick\nItem {\n  Process {}\n}\n"
        found = missing_import_problems(src, "", set())
        self.assertTrue(any("Process" in item for item in found))
        src = "import QtQuick\nimport Quickshell.Io\nItem {\n  Process {}\n}\n"
        self.assertEqual(missing_import_problems(src, "", set()), [])

    def test_plugin_qml_imports_every_type_it_uses(self):
        names = {name[:-4] for name in os.listdir(PLUGIN) if name.endswith(".qml")}
        found = []
        for name in sorted(os.listdir(PLUGIN)):
            if not name.endswith(".qml"):
                continue
            path = os.path.join(PLUGIN, name)
            siblings = names - {name[:-4]}
            with open(path, encoding="utf-8") as handle:
                found.extend(missing_import_problems(handle.read(), path, siblings))
        self.assertEqual(found, [])

    def test_plugin_qml_keeps_editable_fields_inside_an_inactive_loader(self):
        found = []
        for name in sorted(os.listdir(PLUGIN)):
            if not name.endswith(".qml"):
                continue
            path = os.path.join(PLUGIN, name)
            with open(path, encoding="utf-8") as handle:
                found.extend(editable_input_problems(handle.read(), path))
        self.assertEqual(found, [])

    def test_guide_search_fills_the_tab_row(self):
        path = os.path.join(PLUGIN, "GuidePage.qml")
        with open(path, encoding="utf-8") as handle:
            src = handle.read()
        self.assertNotIn("height: searchPlaceholder.implicitHeight", src)
        self.assertIn("anchors.top: parent.top", src)
        self.assertIn("verticalPadding: 0", src)

    def test_guide_shows_build_only_the_visible_rows(self):
        path = os.path.join(PLUGIN, "GuidePage.qml")
        with open(path, encoding="utf-8") as handle:
            src = handle.read()
        self.assertIn("ListView {", src)
        self.assertIn("model: guide.onGrid ? [] : guide.tv.guideShowRows", src)
        self.assertNotIn("showsRepeater", src)
        bar = os.path.join(PLUGIN, "BarWidget.qml")
        with open(bar, encoding="utf-8") as handle:
            widget = handle.read()
        self.assertIn("positionViewAtIndex(root.guideCursor, ListView.Contain)", widget)
        self.assertNotIn("showsList", widget)


if __name__ == "__main__":
    unittest.main()

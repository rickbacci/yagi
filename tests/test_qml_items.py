"""Plugin QML must not put a non-item in an item-only default property.

KeyboardPanel's default property is contentItem, a list of QQuickItem.
A HoverHandler there is how 0.1.1 failed to load the bar:

    Cannot assign object of type "QQuickHoverHandler" to list property
    "contentItem"; expected "QQuickItem"

qmllint is not used: it cannot see the Quickshell modules that define
KeyboardPanel. This walks every plugin QML file instead.
"""

import os
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
        pending = None
        awaiting_value = False
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


if __name__ == "__main__":
    unittest.main()

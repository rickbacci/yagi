pragma Singleton
// Qt 6.12 ships a QtQuick Color singleton. An unqualified QtQuick import
// in this file makes that name win, so the stub never registers and
// Color.accent is undefined. The alias keeps this type's name free.
// Strings assign to QColor the same way a color property does.
import QtQuick as QtQuick

QtQuick.QtObject {
  readonly property string accent: "#7aa2f7"
  readonly property string urgent: "#f7768e"
  readonly property string muted: "#888888"
  readonly property string foreground: "#eeeeee"
  readonly property Popups popups: Popups {}
}

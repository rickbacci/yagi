import QtQuick
Item {
  property string moduleName: ""
  // Quickshell's BarWidget provides the bar thickness under this name.
  property real barSize: 36
  property var bar: ({
    barForeground: "#eeeeee",
    foreground: "#eeeeee",
    fontFamily: "sans-serif",
    vertical: false
  })
}

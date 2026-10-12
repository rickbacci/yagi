import QtQuick
Item {
  property string text: ""
  property string tooltipText: ""
  property string iconText: ""
  property bool selected: false
  property real fontSize: 14
  property color foreground: "#eee"
  signal clicked()
}

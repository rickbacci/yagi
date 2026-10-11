import QtQuick
Item {
  property string iconText: ""
  property string tooltipText: ""
  property string text: ""
  property color foreground: "#eee"
  property string fontFamily: "sans-serif"
  property real fontSize: 14
  property color hoverColor: "#fff"
  signal clicked()
}

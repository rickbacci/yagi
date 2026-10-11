import QtQuick
QtObject {
  property var command
  property bool running: false
  property var stdout
  signal started()
  signal exited(var code)
}

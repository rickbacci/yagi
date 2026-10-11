import QtQuick
Item {
  property var blocked: false
  signal closeRequested()
  signal moveRequested(var dx, var dy)
  signal activateRequested()
  signal deleteRequested()
  signal tabRequested(var direction)
  signal textKey(var t)
}

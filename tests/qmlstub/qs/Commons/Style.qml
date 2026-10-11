pragma Singleton
import QtQuick
QtObject {
  property real gapsOut: 8
  property FontTokens font: FontTokens {}
  property SpacingTokens spacing: SpacingTokens {}
  function space(n) { return Number(n) }
  function normalFillFor(a, b) { return "#333333" }
  function hoverFillFor(a, b) { return "#444444" }
  function selectedFillFor(a, b) { return "#555555" }
}

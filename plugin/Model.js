// Omarchy TV - Model and Helpers

function formatFreq(freqHz) {
  if (!freqHz) return "";
  var mhz = (freqHz / 1000000.0).toFixed(1);
  return mhz + " MHz";
}

function cleanChannelName(name) {
  if (!name) return "Unknown Station";
  return name.replace(/_/g, " ").trim();
}

function bandColor(band, accent, foreground) {
  if (band === "UHF") return accent;
  if (band === "VHF-High") return "#89b4fa"; // Soft Blue
  if (band === "VHF-Low") return "#f9e2af";  // Soft Amber
  return foreground;
}

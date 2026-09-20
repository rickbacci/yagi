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

function networkColor(network, fallback) {
  if (!network) return fallback;
  var net = network.toUpperCase();
  if (net === "NBC") return "#a6e3a1";       // Mint green
  if (net === "ABC") return "#f9e2af";       // Soft amber
  if (net === "FOX") return "#89b4fa";       // Sapphire blue
  if (net === "CBS") return "#cba6f7";       // Mauve purple
  if (net === "PBS") return "#94e2d5";       // Teal
  if (net === "CW") return "#a6e3a1";        // Vibrant green
  if (net === "UNIVISION") return "#f38ba8"; // Coral
  if (net === "ION") return "#89dceb";       // Sky blue
  return fallback;
}

function getChannelBadge(channel) {
  if (!channel) return "OTA";
  if (channel.channel_number) return channel.channel_number;
  if (channel.service_id) return "#" + channel.service_id;
  return "OTA";
}

function getDisplayTitle(channel) {
  if (!channel) return "Unknown Station";
  if (channel.display_name) return channel.display_name;
  return cleanChannelName(channel.name);
}

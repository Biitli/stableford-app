// Teilt das PDF über das Teilen-Menü des Handys (z.B. WhatsApp); sonst WhatsApp mit Text.
async function shareRanking(pdfUrl, filename, text) {
  try {
    const blob = await (await fetch(pdfUrl)).blob();
    const file = new File([blob], filename, { type: "application/pdf" });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      await navigator.share({ files: [file], title: filename, text: text });
      return;
    }
  } catch (e) {
    if (e && e.name === "AbortError") return;
  }
  window.open("https://wa.me/?text=" + encodeURIComponent(text), "_blank");
}
function shareText(text) {
  window.open("https://wa.me/?text=" + encodeURIComponent(text), "_blank");
}

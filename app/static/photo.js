// Fotos (Kamera oder Mediathek) verkleinern und das Formular sofort absenden.
// Grosse iPhone-Fotos werden auf max. 2000 px verkleinert: schneller Upload, und die
// Bildgrenze der Erkennung (5 MB) wird sicher eingehalten.
async function shrink(file, maxSide = 2000) {
  try {
    const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
    const scale = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
    const c = document.createElement("canvas");
    c.width = Math.round(bmp.width * scale);
    c.height = Math.round(bmp.height * scale);
    c.getContext("2d").drawImage(bmp, 0, 0, c.width, c.height);
    const blob = await new Promise((res) => c.toBlob(res, "image/jpeg", 0.85));
    return blob ? new File([blob], (file.name || "foto").replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" }) : file;
  } catch (e) {
    return file;
  }
}

document.addEventListener("change", async (ev) => {
  const input = ev.target;
  if (!input.classList || !input.classList.contains("photo-input") || !input.files.length) return;
  const form = input.form;
  const status = form.querySelector(".photo-status");
  if (status) status.textContent = "Foto wird gelesen … (ca. 20–60 Sekunden)";
  form.querySelectorAll(".photo-input").forEach((x) => { if (x !== input) x.disabled = true; });
  form.querySelectorAll("label.btn").forEach((x) => x.classList.add("busy"));
  try {
    const dt = new DataTransfer();
    for (const f of input.files) dt.items.add(await shrink(f));
    input.files = dt.files;
  } catch (e) { /* ältere Browser: Originalbilder senden */ }
  form.submit();
});

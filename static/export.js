// Export Mobile Info: let the administrator pick where mi.json is saved.
// Chrome/Edge (on https:// or localhost) show a Save dialog where any folder or mapped share can be chosen.
// Elsewhere the link falls back to a normal download.
(function () {
  var link = document.getElementById("export-mi");
  var status = document.getElementById("export-status");
  if (!link || !window.showSaveFilePicker) return;
  link.addEventListener("click", async function (ev) {
    ev.preventDefault();
    status.textContent = "";
    try {
      var handle = await window.showSaveFilePicker({
        suggestedName: "mi.json",
        types: [{ description: "JSON file", accept: { "application/json": [".json"] } }],
      });
      var resp = await fetch(link.dataset.url, { credentials: "same-origin" });
      if (!resp.ok) throw new Error("Server returned " + resp.status);
      var blob = await resp.blob();            // keeps the exact bytes (UTF-8, no BOM)
      var out = await handle.createWritable();
      await out.write(blob);
      await out.close();
      status.textContent = "Saved " + handle.name + ".";
    } catch (err) {
      if (err && err.name === "AbortError") return;   // dialog cancelled
      status.textContent = "Could not save: " + (err && err.message ? err.message : err);
    }
  });
})();

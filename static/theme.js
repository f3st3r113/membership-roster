// Light/dark switch (top right). The choice is remembered in this browser.
(function () {
  var btn = document.getElementById("theme-toggle");
  if (!btn) return;
  var root = document.documentElement;
  function paint() {
    var dark = root.getAttribute("data-theme") === "dark";
    btn.innerHTML = dark ? "&#9728;" : "&#9790;";          // sun when dark, moon when light
    var label = dark ? "Switch to light mode" : "Switch to dark mode";
    btn.setAttribute("aria-label", label);
    btn.title = label;
  }
  btn.addEventListener("click", function () {
    var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
    root.setAttribute("data-theme", next);
    try { localStorage.setItem("cfd-theme", next); } catch (e) {}
    paint();
  });
  paint();
})();

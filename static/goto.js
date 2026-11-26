// "Go to" box on the member form: looks names up on demand (2+ characters, max 10 results)
// instead of embedding every member's name in the page.
(function () {
  var input = document.getElementById("goto-q");
  var list = document.getElementById("goto-results");
  if (!input || !list) return;
  var timer = null, seq = 0;
  function hide() { list.hidden = true; list.innerHTML = ""; }
  function show(items) {
    list.innerHTML = "";
    if (!items.length) {
      var li = document.createElement("li"); li.className = "none"; li.textContent = "No match"; list.appendChild(li);
    }
    items.forEach(function (it) {
      var li = document.createElement("li"), a = document.createElement("a");
      a.href = it.url; a.textContent = it.name; li.appendChild(a); list.appendChild(li);
    });
    list.hidden = false;
  }
  input.addEventListener("input", function () {
    clearTimeout(timer);
    var q = input.value.trim();
    if (q.length < 2) { hide(); return; }
    timer = setTimeout(function () {
      var mine = ++seq;
      fetch(input.dataset.url + "?q=" + encodeURIComponent(q), { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : []; })
        .then(function (items) { if (mine === seq) show(items); })
        .catch(hide);
    }, 200);
  });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Escape") hide();
    if (e.key === "Enter") { var a = list.querySelector("a"); if (a) { e.preventDefault(); location.href = a.href; } }
  });
  document.addEventListener("click", function (e) { if (!list.contains(e.target) && e.target !== input) hide(); });
})();

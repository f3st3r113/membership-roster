// "Find application": search the applications folder by name, then fill blank member form fields from the chosen PDF.
(function () {
  var box = document.querySelector(".app-search");
  if (!box) return;
  var last = document.getElementById("app-last"), first = document.getElementById("app-first");
  var msg = document.getElementById("app-msg"), list = document.getElementById("app-results");
  var LABELS = {last_name: "Last Name", first_name: "First Name", address: "Street", city: "City", state: "State",
    zip: "Zip", mobile_phone: "Mobile Phone", email: "E-mail", membership_class: "Membership Class",
    response_type: "Response Type"};

  function say(text, bad) { msg.textContent = text; msg.className = "app-msg" + (bad ? " bad" : ""); }
  function get(url) {
    return fetch(url, {credentials: "same-origin", headers: {Accept: "application/json"}}).then(function (r) {
      return r.json().catch(function () { return {error: "Unexpected answer from the server."}; });
    });
  }

  function search() {
    list.innerHTML = "";
    if (!last.value.trim()) { say("Type a last name first.", true); return; }
    say("Searching…");
    get(box.dataset.search + "?last=" + encodeURIComponent(last.value.trim()) +
        "&first=" + encodeURIComponent(first.value.trim())).then(function (d) {
      if (d.error) { say(d.error, true); return; }
      if (!d.files.length) { say("No application files found for that name."); return; }
      say(d.files.length + " file" + (d.files.length > 1 ? "s" : "") + " found. Choose one:");
      d.files.forEach(function (f) {
        var li = document.createElement("li"), b = document.createElement("button");
        b.type = "button"; b.className = "btn"; b.textContent = "Use";
        b.addEventListener("click", function () { use(f); });
        li.appendChild(b);
        li.appendChild(document.createTextNode(" " + f.name + "  (modified " + f.modified + ")"));
        list.appendChild(li);
      });
    });
  }

  function use(f) {
    say("Reading " + f.name + "…");
    get(box.dataset.fields.replace("ITEM", encodeURIComponent(f.id)) +
        "?last=" + encodeURIComponent(last.value.trim()) + "&first=" + encodeURIComponent(first.value.trim())).then(function (d) {
      if (d.error) { say(d.error, true); return; }
      var filled = [], kept = [];
      Object.keys(d.fields).forEach(function (k) {
        var el = document.querySelector('.member-form [name="' + k + '"]');
        if (!el || el.disabled) return;
        if (el.value.trim()) { if (el.value.trim() !== d.fields[k]) kept.push(LABELS[k] || k); return; }
        if (el.tagName === "SELECT") {
          var ok = Array.prototype.some.call(el.options, function (o) { return o.value === d.fields[k] || o.text === d.fields[k]; });
          if (!ok) return;
        }
        el.value = d.fields[k];
        el.dispatchEvent(new Event("input", {bubbles: true}));
        filled.push(LABELS[k] || k);
      });
      var folder = document.querySelector('.member-form [name="create_folder"]');
      if (folder) folder.checked = true;
      if (d.notes.length) {  // something needs a look: show the details
        var text = "Filled from " + d.file + ": " + (filled.join(", ") || "nothing new") + ". " + d.notes.join(" ");
        if (kept.length) text += " Already filled, left alone: " + kept.join(", ") + ".";
        say(text, true);
      } else {
        say("Complete");
      }
      list.innerHTML = "";
    });
  }

  document.getElementById("app-go").addEventListener("click", search);
  [last, first].forEach(function (el) {
    el.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); search(); } });
  });
})();

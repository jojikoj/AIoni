/* AIの鬼 サイト内検索 — サーバー不要。静的JSONを読んで絞り込む。 */
(function () {
  "use strict";
  var cfg = window.AIONI_SEARCH;
  if (!cfg) return;

  var input = document.getElementById("q");
  var out = document.getElementById("search-results");
  var status = document.getElementById("search-status");
  var data = null, loading = false;

  function esc(s) {
    return String(s || "").replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function load(cb) {
    if (data) return cb();
    if (loading) return;
    loading = true;
    status.textContent = cfg.strings.loading;
    fetch(cfg.index)
      .then(function (r) { return r.json(); })
      .then(function (j) { data = j; loading = false; cb(); })
      .catch(function () { loading = false; status.textContent = "—"; });
  }

  function score(item, terms) {
    var t = (item.t || "").toLowerCase();
    var d = (item.d || "").toLowerCase();
    var s = 0;
    for (var i = 0; i < terms.length; i++) {
      var w = terms[i];
      if (t.indexOf(w) !== -1) s += t.indexOf(w) === 0 ? 12 : 8;
      else if (d.indexOf(w) !== -1) s += 2;
      else return 0;              // 全語を含むものだけ採用（AND検索）
    }
    return s;
  }

  function render(q) {
    var terms = q.toLowerCase().split(/\s+/).filter(Boolean);
    if (!terms.length) {
      out.innerHTML = ""; status.textContent = cfg.strings.prompt; return;
    }
    var hits = [];
    for (var i = 0; i < data.length; i++) {
      var s = score(data[i], terms);
      if (s > 0) hits.push({ item: data[i], s: s });
    }
    hits.sort(function (a, b) { return b.s - a.s; });
    hits = hits.slice(0, 60);

    if (!hits.length) { out.innerHTML = ""; status.textContent = cfg.strings.none; return; }
    status.textContent = cfg.strings.hits.replace("{n}", hits.length);

    var html = "";
    for (var j = 0; j < hits.length; j++) {
      var it = hits[j].item;
      var href = it.x ? it.u : cfg.rel + it.u;      // x=1 は外部リンク
      var ext = it.x ? ' target="_blank" rel="noopener"' : "";
      html += '<a class="search-hit" href="' + esc(href) + '"' + ext + '>' +
              '<div class="search-hit-meta">' +
              '<span class="pill ghost">' + esc(cfg.kinds[it.k] || it.k) + "</span>" +
              (it.s ? '<span class="search-hit-src">' + esc(it.s) + "</span>" : "") +
              "</div>" +
              '<h3 class="search-hit-title">' + esc(it.t) + "</h3>" +
              (it.d ? '<p class="search-hit-desc">' + esc(it.d) + "</p>" : "") +
              "</a>";
    }
    out.innerHTML = html;
  }

  var timer;
  function onInput() {
    clearTimeout(timer);
    var q = input.value.trim();
    timer = setTimeout(function () { load(function () { render(q); }); }, 130);
  }

  input.addEventListener("input", onInput);

  // URLの ?q= を初期値にする（SearchAction からの遷移に対応）
  var m = location.search.match(/[?&]q=([^&]*)/);
  if (m) {
    input.value = decodeURIComponent(m[1].replace(/\+/g, " "));
    onInput();
  } else {
    status.textContent = cfg.strings.prompt;
  }
})();

/* AIの鬼 — フロントエンド挙動（依存なし・軽量） */
(function () {
  "use strict";

  // --- モバイルナビ ---
  var toggle = document.querySelector(".nav-toggle");
  var nav = document.getElementById("sidebar");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
    // サイドバー外をクリックしたら閉じる
    document.addEventListener("click", function (e) {
      if (!nav.classList.contains("open")) return;
      if (nav.contains(e.target) || toggle.contains(e.target)) return;
      nav.classList.remove("open");
      toggle.setAttribute("aria-expanded", "false");
    });
  }

  // --- 打ち上げライブカウントダウン ---
  var counters = Array.prototype.slice.call(document.querySelectorAll(".net-countdown[data-net]"));
  if (counters.length) {
    var lang = document.body.getAttribute("data-lang") || "en";
    function pad(n) { return n < 10 ? "0" + n : "" + n; }
    function render() {
      var now = Date.now();
      counters.forEach(function (el) {
        var net = Date.parse(el.getAttribute("data-net"));
        if (isNaN(net)) return;
        var s = Math.floor((net - now) / 1000);
        if (s <= 0) { el.textContent = lang === "ja" ? "まもなく" : "T-0"; return; }
        var d = Math.floor(s / 86400); s -= d * 86400;
        var h = Math.floor(s / 3600); s -= h * 3600;
        var m = Math.floor(s / 60); var sec = s - m * 60;
        if (d > 0) {
          el.textContent = lang === "ja"
            ? "T-" + d + "日 " + h + "時間 " + pad(m) + "分"
            : "T-" + d + "d " + pad(h) + "h " + pad(m) + "m";
        } else {
          el.textContent = "T-" + pad(h) + ":" + pad(m) + ":" + pad(sec);
        }
      });
    }
    render();
    setInterval(render, 1000);
  }

  // --- 言語スイッチ: 手動で選んだ言語を記憶し、以後は自動振り分けしない ---
  var langLinks = document.querySelectorAll(".lang-switch a[hreflang]");
  Array.prototype.forEach.call(langLinks, function (a) {
    a.addEventListener("click", function () {
      try { localStorage.setItem("aioni-lang", a.getAttribute("hreflang")); } catch (e) {}
    });
  });
})();

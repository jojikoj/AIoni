// AI可視性チェッカー。会社名を diagnose API に送り、AIによる認識状況を表示する。
// API は ai-oni.com オリジンからのみ許可（Origin制限）。結果は score / summary / sources。
(function () {
  var cfg = window.AIONI_CHECK || {};
  var form = document.getElementById('check-form');
  var input = document.getElementById('check-company');
  var btn = document.getElementById('check-btn');
  var out = document.getElementById('check-result');
  var cta = document.getElementById('check-cta');
  if (!form || !cfg.endpoint) return;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  // score(0-100) を4段階のラベルに落とす。
  function levelLabel(score) {
    if (score >= 75) return { t: '十分に認識されている', c: 'lv3' };
    if (score >= 50) return { t: 'ある程度認識されている', c: 'lv2' };
    if (score >= 25) return { t: '認識が弱い', c: 'lv1' };
    return { t: 'ほとんど認識されていない', c: 'lv0' };
  }

  function render(d) {
    var lv = levelLabel(d.score || 0);
    var srcs = (d.sources || []).slice(0, 6).map(function (s) {
      return '<li>' + esc(s.title || s.uri) + '</li>';
    }).join('');
    out.innerHTML =
      '<div class="check-score ' + lv.c + '">' +
        '<span class="check-score-num">' + (d.score || 0) + '<small>/100</small></span>' +
        '<span class="check-score-label">' + esc(lv.t) + '</span>' +
      '</div>' +
      '<p class="check-summary">' + esc(d.summary || '') + '</p>' +
      (srcs ? '<div class="check-sources"><span>AIが参照した情報源</span><ul>' + srcs + '</ul></div>' : '') +
      '<p class="check-disclaimer">※ これはAIが現在どう認識しているかの実測であり、' +
      '検索での上位表示や引用を保証するものではありません。</p>';
    out.hidden = false;
    if (cta) cta.hidden = false;
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var company = (input.value || '').trim();
    if (!company) { input.focus(); return; }
    btn.disabled = true;
    var orig = btn.textContent;
    btn.textContent = '診断中…';
    out.hidden = false;
    out.innerHTML = '<p class="check-loading">AIに問い合わせています。数十秒かかることがあります…</p>';
    if (cta) cta.hidden = true;

    fetch(cfg.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ company: company })
    })
      .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
      .then(function (res) {
        if (!res.ok || res.j.error) {
          out.innerHTML = '<p class="check-error">診断できませんでした。' +
            esc((res.j && res.j.error) || '時間をおいて再度お試しください。') + '</p>';
          return;
        }
        render(res.j);
      })
      .catch(function () {
        out.innerHTML = '<p class="check-error">通信に失敗しました。時間をおいて再度お試しください。</p>';
      })
      .finally(function () { btn.disabled = false; btn.textContent = orig; });
  });
})();

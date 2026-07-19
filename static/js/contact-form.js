/* 問い合わせフォーム。
 *
 * 静的サイトのためサーバー側でPOSTを受けられない。
 * 2つの経路を用意し、設定に応じて切り替える:
 *
 *   1. FORM_ENDPOINT が設定されていれば、そこへ非同期POSTする
 *      （Web3Forms / Formspree などのフォームサービスを想定）
 *   2. 未設定なら、入力内容を整形してメーラーを開く
 *      （確実に動くフォールバック。宛先・件名・本文が入力済みになる）
 */
(function () {
  "use strict";
  var cfg = window.AIONI_FORM;
  var form = document.getElementById("inquiry-form");
  if (!cfg || !form) return;

  var status = document.getElementById("form-status");

  function val(name) {
    var el = form.elements[name];
    return el ? el.value.trim() : "";
  }

  function buildBody() {
    var lines = [
      cfg.labels.kind + "：" + val("kind"),
      "",
      cfg.labels.company + "：" + val("company"),
      cfg.labels.name + "：" + val("name"),
      cfg.labels.email + "：" + val("email"),
      cfg.labels.tel + "：" + (val("tel") || "-"),
      cfg.labels.site + "：" + (val("site") || "-"),
      "",
      cfg.labels.message + "：",
      val("message"),
      "",
      "――――――――――",
      cfg.labels.sent_from,
    ];
    return lines.join("\n");
  }

  function setStatus(msg, kind) {
    status.textContent = msg;
    status.className = "form-status" + (kind ? " is-" + kind : "");
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();

    // ブラウザ標準のバリデーションを使う
    if (!form.checkValidity()) {
      form.reportValidity();
      return;
    }

    var subject = "[AIの鬼] " + val("kind");
    var body = buildBody();

    // --- 経路1: 受信プログラムへ直接POST ---
    if (cfg.endpoint) {
      setStatus(cfg.strings.sending, "sending");
      // 共通GAS（コンテンツ部）の仕様に合わせる。
      // site でメディアを判別し、type で申込種別を決める。
      // origin は送信元チェックに使われる。
      var payload = {
        site: cfg.site_key || "aioni",
        type: "consult",
        // 受信側(GAS)の許可リストは正規のURLで登録されている。
        // HTTPS証明書の発行前はサイトが http で動くため location.origin を
        // そのまま送ると弾かれる。正規のURLを送る。
        // この値はもともとクライアントが自由に送れるもので、
        // 認証ではなく送信元の目印として使われている。
        origin: cfg.site_origin || location.origin,
        kind: val("kind"),
        company: val("company"),
        name: val("name"),
        email: val("email"),
        tel: val("tel"),
        url: val("site"),
        message: val("message") + "\n\n【ご用件】" + val("kind"),
        fax: val("hp"),        // ハニーポット（GAS側の想定フィールド名）
        // FormSubmit 互換（エンドポイントを戻した場合に備える）
        _subject: subject,
        _captcha: "false",
        _template: "table"
      };

      // Google Apps Script はCORSプリフライトに応答しないため、
      // Content-Type を text/plain にして「単純リクエスト」として送る。
      // これによりプリフライトが発生せず、追加設定なしで送信できる。
      var isGas = cfg.endpoint.indexOf("script.google.com") !== -1;
      var opts = isGas
        ? { method: "POST", body: JSON.stringify(payload),
            headers: { "Content-Type": "text/plain;charset=utf-8" } }
        : { method: "POST", body: JSON.stringify(payload),
            headers: { "Content-Type": "application/json", Accept: "application/json" } };

      fetch(cfg.endpoint, opts)
        .then(function (r) { return r.json().catch(function () { return { success: r.ok }; }); })
        .then(function (j) {
          // FormSubmit は success を文字列で返すため両方を見る
          // GASは {ok:true}、FormSubmitは {success:"true"} を返す
          var ok = j.ok === true || j.success === true || j.success === "true";
          if (ok) {
            form.reset();
            setStatus(cfg.strings.sent, "ok");
          } else {
            // GASはエラー理由を返すので、そのまま見せた方が親切
            setStatus(j.error || cfg.strings.failed, "error");
          }
        })
        .catch(function () { setStatus(cfg.strings.failed, "error"); });
      return;
    }

    // 送信先が未設定の場合はフォームを使えないことを明示する。
    // メールアドレスをHTMLに埋め込むとスパム収集ボットに拾われるため、
    // mailto へのフォールバックは行わない。
    setStatus(cfg.strings.failed, "error");
  });

  // URLの ?kind= で用件を初期選択する（各所のCTAから遷移する用）
  var m = location.search.match(/[?&]kind=([^&]*)/);
  if (m) {
    var want = decodeURIComponent(m[1].replace(/\+/g, " "));
    var sel = form.elements["kind"];
    if (sel) {
      for (var i = 0; i < sel.options.length; i++) {
        if (sel.options[i].value === want) { sel.selectedIndex = i; break; }
      }
    }
  }
})();

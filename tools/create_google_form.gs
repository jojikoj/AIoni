/**
 * AIの鬼 問い合わせフォームを自動生成する Google Apps Script。
 *
 * 使い方（3分で終わります）:
 *   1. https://script.google.com/ を開き「新しいプロジェクト」
 *   2. このファイルの中身を全部貼り付ける
 *   3. 上部の「実行」を押す（初回は権限の承認を求められます）
 *   4. 実行ログに出る「埋め込みURL」をコピーして小嶋さんへ
 *
 * 実行すると:
 *   - 質問項目つきのフォームが作られる
 *   - 回答をまとめるスプレッドシートが作られる
 *   - 回答があったときにメール通知が届くよう設定される
 */

function createAIの鬼Form() {
  var NOTIFY_EMAIL = 'joe@gtoe.info';   // 通知先。変更する場合はここ

  var form = FormApp.create('AIの鬼 お問い合わせ');
  form.setTitle('AIの鬼 お問い合わせ');
  form.setDescription(
    'AIの鬼（宇宙産業サプライチェーン・メディア）へのお問い合わせフォームです。\n' +
    '宇宙産業への参入相談、企業データベースへの掲載（無料）、広告掲載、' +
    '取材・情報提供のいずれもこちらから承ります。\n' +
    '通常2営業日以内にご返信します。'
  );

  // --- ご用件 ---
  form.addMultipleChoiceItem()
    .setTitle('ご用件')
    .setRequired(true)
    .setChoiceValues([
      '宇宙産業への参入について相談したい',
      '企業データベースへの掲載を希望する（無料）',
      '広告掲載について相談したい',
      '取材・情報提供',
      'その他'
    ]);

  // --- 会社情報 ---
  form.addTextItem().setTitle('貴社名').setRequired(true);
  form.addTextItem().setTitle('ご担当者名').setRequired(true);

  form.addTextItem()
    .setTitle('メールアドレス')
    .setRequired(true)
    .setValidation(
      FormApp.createTextValidation()
        .requireTextIsEmail()
        .setHelpText('正しいメールアドレスを入力してください')
        .build()
    );

  form.addTextItem().setTitle('電話番号（任意）').setRequired(false);
  form.addTextItem().setTitle('貴社サイトURL（任意）').setRequired(false);

  // --- 事業内容（参入相談の判断材料になる） ---
  form.addCheckboxItem()
    .setTitle('主な技術・事業領域（複数選択可）')
    .setRequired(false)
    .setChoiceValues([
      '金属加工・機械加工',
      '樹脂・複合材',
      '電子部品・基板',
      '光学・センサ',
      '素材・材料',
      '試験・検査・計測',
      'ソフトウェア・データ解析',
      '設計・エンジニアリング',
      'その他'
    ]);

  form.addMultipleChoiceItem()
    .setTitle('宇宙分野での取引実績')
    .setRequired(false)
    .setChoiceValues([
      'すでに取引がある',
      '過去に問い合わせ・商談をしたことがある',
      'まだない（これから検討）'
    ]);

  form.addParagraphTextItem()
    .setTitle('ご相談内容')
    .setRequired(true)
    .setHelpText('例）金属加工を行っています。自社の技術が宇宙分野で活かせるか相談したい。');

  // --- 回答先スプレッドシートを作成して紐付け ---
  var ss = SpreadsheetApp.create('AIの鬼 問い合わせ回答');
  form.setDestination(FormApp.DestinationType.SPREADSHEET, ss.getId());

  // --- 回答時にメール通知 ---
  form.setCollectEmail(false);
  ScriptApp.newTrigger('notifyOnSubmit')
    .forForm(form)
    .onFormSubmit()
    .create();
  PropertiesService.getScriptProperties().setProperty('NOTIFY_EMAIL', NOTIFY_EMAIL);

  // --- 結果を出力 ---
  var embedUrl = form.getPublishedUrl().replace('/viewform', '/viewform?embedded=true');
  Logger.log('==============================================');
  Logger.log('フォーム作成が完了しました。');
  Logger.log('');
  Logger.log('▼ 埋め込みURL（これをClaudeに渡してください）');
  Logger.log(embedUrl);
  Logger.log('');
  Logger.log('▼ 編集用URL');
  Logger.log(form.getEditUrl());
  Logger.log('');
  Logger.log('▼ 回答スプレッドシート');
  Logger.log(ss.getUrl());
  Logger.log('==============================================');
  return embedUrl;
}

/** 回答があったときにメールで通知する */
function notifyOnSubmit(e) {
  var to = PropertiesService.getScriptProperties().getProperty('NOTIFY_EMAIL');
  if (!to || !e || !e.response) return;

  var items = e.response.getItemResponses();
  var lines = [];
  for (var i = 0; i < items.length; i++) {
    var r = items[i].getResponse();
    lines.push(items[i].getItem().getTitle() + '：' + (Array.isArray(r) ? r.join(', ') : r));
  }
  MailApp.sendEmail({
    to: to,
    subject: '[AIの鬼] 新しいお問い合わせがありました',
    body: lines.join('\n') + '\n\n――――――――――\nAIの鬼 お問い合わせフォームより'
  });
}

# tools/

## 問い合わせ受付について

**このメディア専用のGASは置かない。**

問い合わせ受付は**コンテンツ部の共通GAS**を使う。
メディアごとに同じ仕組みを作ると、デプロイもURL管理も二重になるため。

- 実体: `claude_AIR/TOEcompany/コンテンツ部/共通/gas/受付.gs`
- 手順: `claude_AIR/TOEcompany/コンテンツ部/共通/gas/設置手順.md`

かつてここに `form_receiver.gs` を置いていたが、共通版に統合して削除した（2026-07-18）。

## 現在の接続先

サイトのフォーム送信先は `aioni/config.py` の `FORM_ENDPOINT` で決まる。

| 状態 | 値 |
|---|---|
| 現在 | FormSubmit（外部サービス・有効化済み・稼働中） |
| 移行先 | 共通GASのウェブアプリURL（デプロイ後に差し替える） |

共通GASをデプロイしたら、`FORM_ENDPOINT` をそのURLに変更するだけで切り替わる。

## create_google_form.gs

Googleフォームを自動生成するスクリプト。
FormSubmit と共通GAS のどちらも使わず、Googleフォーム埋め込みで運用したい場合の選択肢として残してある。
現状は使っていない。

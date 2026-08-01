# デプロイ手順

AIの鬼 は静的サイトで、**GitHub Pages** で配信している。
データ収集と記事生成はローカル（Mac）で行い、生成物を push するだけで公開される。

```
[ローカル Mac]  collect → 記事生成 → git push
                                        ↓
                          [GitHub Pages] が ai-oni.com で公開
```

> **サイト本体は Vercel に置かない。** 無料枠（Hobby）が商用利用不可のため、
> 営業導線を持つ本サイトの配信元としては選べない。GitHub Pages（無料・商用可）に一本化している。
>
> ただし**トップの AI可視性チェッカーだけは Vercel を使う**。会社名を受け取ってAIに
> 問い合わせる処理はサーバーが要り、静的ホスティングでは動かないため。
> エンドポイントは `aioni/config.py` の `DIAGNOSE_ENDPOINT` に一元管理している
> （Vercel を再デプロイして本番URLが変わったらここを直す）。

---

## 通常の更新

```bash
./tools/deploy.sh    # origin/main を取り込む → リンク検査 → 生成 → gh-pages へ push → IndexNow
```

`gh-pages` ブランチに `dist/` を push する方式。push を検知して GitHub Pages が公開する。

> ⚠️ **deploy.sh は毎回 `push -f` で全上書きする。** 実行機が `main` を取り込まないまま
> 日次を回すと、その間に入れた改修が公開サイトから丸ごと消える（2026-08-01 に発生）。
> エラーは出ないので気づけない。そのため deploy.sh は冒頭で `origin/main` より遅れて
> いないかを確認し、遅れていれば取り込む。取り込めなければ公開せず中止する。
>
> 公開後は `python3 tools/health_check.py` で、鮮度と「載っているべき目印」を確認できる。

---

## 初期設定（一度だけ）

### 1. DNS を設定（ムームードメイン）

ムームードメイン → **ムームーDNS** → `ai-oni.com` の「変更」→ カスタム設定

| サブドメイン | 種別 | 内容 |
|---|---|---|
| （空欄） | A | `185.199.108.153` |
| （空欄） | A | `185.199.109.153` |
| （空欄） | A | `185.199.110.153` |
| （空欄） | A | `185.199.111.153` |
| `www` | CNAME | `jojikoj.github.io` |

独自ドメインは `aioni/config.py` の `SITE_DOMAIN` から `dist/CNAME` に書き出される。

### 2. HTTPS を有効化

DNS が反映されたら <https://github.com/jojikoj/AIoni/settings/pages> で
**Enforce HTTPS** にチェックを入れる。

---

## 公開後にやること（チェックリスト）

`claude_AIR/TOEcompany/コンテンツ部/共通/公開後チェックリスト.md` に従う。

- [ ] Search Console にサイトマップ（`https://ai-oni.com/sitemap.xml`）を登録
- [ ] Bing / IndexNow
- [ ] GA4（測定ID は `aioni/config.py` の `GA4_MEASUREMENT_ID`）
- [ ] 問い合わせフォームの疎通確認（共通GAS）

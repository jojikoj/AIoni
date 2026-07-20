# デプロイ手順

AIの鬼 は静的サイトで、**GitHub Pages** で配信している。
データ収集と記事生成はローカル（Mac）で行い、生成物を push するだけで公開される。

```
[ローカル Mac]  collect → 記事生成 → git push
                                        ↓
                          [GitHub Pages] が ai-oni.com で公開
```

> Vercel は使わない。無料枠（Hobby）が商用利用不可のため、営業導線を持つ本サイトでは選べない。
> 過去に Vercel 構成を検討した経緯があるが、GitHub Pages（無料・商用可）に一本化した。

---

## 通常の更新

```bash
./run.sh publish     # 収集 → 生成 → commit → gh-pages へ push
```

`gh-pages` ブランチに `dist/` を push する方式。push を検知して GitHub Pages が公開する。

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

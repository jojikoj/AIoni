# デプロイ手順

AIの鬼 は静的サイトなので、GitHub Pages でも Vercel でも配信できる。
**どちらでもデータ収集と翻訳はローカル（Mac）で行う**点は変わらない。

```
[ローカル Mac]  collect → translate(claude CLI) → git push
                                                    ↓
                                    [GitHub Pages] または [Vercel] が公開
```

---

## A. Vercel で公開する（CLI不要・ブラウザだけで完結）

### 1. リポジトリを繋ぐ

1. <https://vercel.com/new> を開く（GitHubアカウントでログイン）
2. `jojikoj/AIの鬼` を **Import**
3. 設定は `vercel.json` が自動で読まれるので**そのまま Deploy** を押す
   - Build Command: `python3 -m pip install ... && python3 -m uchuchu.build`（自動設定）
   - Output Directory: `dist`（自動設定）

初回デプロイが終わると `https://uchuchu-xxxx.vercel.app` で見られる。

### 2. 独自ドメインを設定

1. Vercel のプロジェクト → **Settings → Domains**
2. `uchuchu.tech` を追加（`www.uchuchu.tech` も追加すると自動でリダイレクトされる）
3. ムームードメイン → **ムームーDNS** → `uchuchu.tech` の「変更」→ カスタム設定

| サブドメイン | 種別 | 内容 |
|---|---|---|
| （空欄） | A | `76.76.21.21` |
| `www` | CNAME | `cname.vercel-dns.com` |

HTTPS証明書は Vercel が自動で発行するので、こちら側の操作は不要。

### 3. 以降の更新

```bash
./run.sh publish     # 収集 → 翻訳 → 生成 → commit & push
```

push を検知して Vercel が自動でビルド・公開する。GitHub Actions は不要。

> **補足**: Vercel の無料枠（Hobby）は商用利用不可。
> 将来 AIの鬼 に広告等を入れて収益化する場合は有料プラン（$20/月〜）が必要になる。

> **もしビルドが失敗したら**: Vercel のビルド環境に `python3` が無い場合は、
> Settings → General → Build Command を空にし、`dist/` をコミットする運用に切り替える
> （`.gitignore` から `dist/` を外し、`./run.sh build` の結果を push する）。

---

## B. GitHub Pages で公開する（現在の構成）

### 1. DNS を設定

ムームードメイン → **ムームーDNS** → `uchuchu.tech` の「変更」→ カスタム設定

| サブドメイン | 種別 | 内容 |
|---|---|---|
| （空欄） | A | `185.199.108.153` |
| （空欄） | A | `185.199.109.153` |
| （空欄） | A | `185.199.110.153` |
| （空欄） | A | `185.199.111.153` |
| `www` | CNAME | `jojikoj.github.io` |

### 2. HTTPS を有効化

DNS が反映されたら <https://github.com/jojikoj/AIの鬼/settings/pages> で
**Enforce HTTPS** にチェックを入れる。

### 3. 以降の更新

```bash
./run.sh publish
```

現在は `gh-pages` ブランチに `dist/` を直接 push する方式で配信している。

GitHub Actions による自動ビルドを使いたい場合は、先に一度だけ次を実行して
トークンに `workflow` 権限を付ける（ブラウザ認証が必要）。

```bash
gh auth refresh -h github.com -s workflow
```

その後 `.github/workflows/deploy.yml` を push すれば、push 検知で自動公開される。

---

## どちらを選ぶか

| | GitHub Pages | Vercel |
|---|---|---|
| 費用 | 無料（商用可） | 無料枠は商用不可 |
| DNS設定 | A×4 + www | A×1 + www |
| HTTPS | DNS反映後に手動でチェック | 自動 |
| 自動デプロイ | Actions に `workflow` 権限が必要 | push だけで動く |
| プレビューURL | なし | ブランチごとに自動生成 |

表示速度はどちらも静的配信のため、体感差が出るほどの違いはない。
**両方に同時にデプロイしておき、DNS の向き先で本番を選ぶこともできる。**

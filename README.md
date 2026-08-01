# AIの鬼 👹

**中小企業のAI実践・実測ラボ。** — 株式会社TOEが自社の業務でAIを動かした記録と、
AI検索での見え方を実際に測った数字を公開する静的サイト。あわせて国内外のAIニュースと
arXiv の研究プレプリントを集約する。

🌐 <https://ai-oni.com>

> **運用中のAPI従量課金はゼロ。** 収集はすべて無料の公開API/RSS、翻訳と要約はローカルの
> Claude Code（`claude` CLI／`--model haiku`）、公開は GitHub Pages。

---

## 何を載せているか

| 区分 | 内容 | 規模 | 出どころ |
|---|---|---|---|
| 記事 | 編集部が書く実践記録・実測・解説 | 208本 | `content/articles/*.ja.md` |
| ニュース | 国内外のAIニュースを1日2回集約 | 保持3000件・一覧600件 | 15ソース（OpenAI / Google AI / Hugging Face / MIT Tech Review / TechCrunch / The Verge / ITmedia AI+ / Zenn / Qiita ほか） |
| 研究動向 | cs.AI / cs.CL / cs.LG / cs.CV の最新プレプリント | 最大250件 | arXiv API |

記事は7カテゴリに分かれる（`config.ARTICLE_CATEGORIES`）。

| カテゴリ | URL | 中身 |
|---|---|---|
| AI実践室 | `/jissen/` | 実際に動かしている仕組みの記録。処理件数・所要時間・失敗件数を実ログで裏取り |
| AI検索観測所 | `/kansoku/` | ChatGPT・Perplexity・AI Overviews を実際に測った結果 |
| 失敗の鬼 | `/shippai/` | 自社で起きた失敗。中小企業向けの教訓に着地させる |
| AI仕事術 | `/shigoto/` | 実務で使える手順 |
| AI解体新書 | `/kaisetsu/` | 外部の研究・調査を中小企業向けに読み解く |
| 今週のAI | `/weekly/` | 集めたニュースから中小企業に必要なものを選ぶ（記事0本のあいだは noindex） |
| 中の鬼 | `/naka/` | 中の人の雑記 |

## 積み上げの仕組み

- **アーカイブ蓄積**: 収集のたびに上書きせず、既存データへ新着を統合する（URLで重複排除）。
  上限は `NEWS_LIMIT`（3000件）。**この値は「個別ページが存在し続けるか」を直接決める**——
  短くすると、Googleにインデックスされた頃にはページが消えて404になる（config.py のコメント参照）。
- **一覧と保持を分離**: 一覧に出すのは `NEWS_LIST_LIMIT`（600件）。個別ページは保持分すべて作る。
- **翻訳キャッシュ**: 訳した記事は `data/translations.json` にURLキーで保存し、次回は再翻訳しない。
- **薄いページは noindex**: 自社の解説（`body_long`）が無いニュース個別ページと、記事0本の
  カテゴリページは `noindex` にし sitemap からも外す。中身が入れば自動で index に戻る。
- **ページ分割**: 一覧は1ページ30件（`PAGE_SIZE`）。2ページ目以降は `noindex, follow`。

## セットアップ

```bash
pip install -r requirements.txt
```

翻訳・要約はローカルの [Claude Code](https://claude.com/claude-code)（`claude` コマンド）を使う。
バッチは必ず `--model haiku`（`AIONI_BATCH_MODEL`）。指定しないと対話用の枠を食い潰す。

## 使い方

```bash
./run.sh all        # 収集 → 生成 → プレビュー (http://localhost:8765)
./run.sh collect    # データ収集＋翻訳のみ
./run.sh build      # サイト生成のみ
./run.sh serve      # 生成してプレビュー
./run.sh publish    # 収集 → 生成 → data/ を main にコミット＆push（※公開ではない）

./tools/deploy.sh   # 公開。main を取り込む → 生成 → gh-pages へ push → IndexNow
python3 tools/health_check.py --notify   # 公開サイトが生きているかの点検
```

> `run.sh publish` と `tools/deploy.sh` は別物。前者は収集データを `main` に残すだけで、
> 公開サイトは変わらない。実際に ai-oni.com を更新するのは後者。

## 更新の流れ

```
[実行機 Mac mini]                          [GitHub]
 collect   ── 無料の公開API/RSSから収集
    │
 fulltext  ── 配信元の本文を取得（robots.txt を尊重）
    │
 解説生成   ── claude CLI (haiku) で約800字の独自解説
    │
 deploy.sh ── origin/main を取り込む → build → gh-pages へ push
                                            → https://ai-oni.com
```

**収集・翻訳・生成をローカルで行うのがこの構成の要。** GitHub Actions 上では `claude` が
使えないため、Actions は使わず、実行機が生成物を `gh-pages` に push する。

### ⚠️ 実行機が古いコードで公開を上書きする事故に注意

`deploy.sh` は毎回 `push -f` で全上書きする。**実行機が `main` を取り込まないまま日次を
回すと、その間に入れた改修が公開サイトから丸ごと消える**（2026-08-01 に発生。記事末の
相談バナー・関連記事欄・画像の軽量化が一度に消えた）。エラーは出ない。

対策として `deploy.sh` の冒頭で `origin/main` より遅れていないか確認し、遅れていれば
取り込む。取り込めなければ公開せず中止する。加えて `health_check.py` が
「公開サイトに載っているべき目印」を検査する。

## 点検

```bash
python3 tools/health_check.py           # 鮮度＋目印（cron向け。--notify で macOS 通知）
python3 tools/check_links.py            # 内部リンク切れ（deploy.sh が自動実行）
python3 tools/weekly_review.py          # 薄い記事・孤立記事・画像なしの棚卸し
python3 tools/searchconsole_report.py   # Search Console のクエリとサイトマップ状態
python3 tools/optimize_images.py --dry  # 掲載写真の再圧縮量を試算
```

## 独自ドメイン（ai-oni.com）

`aioni/config.py` の `SITE_DOMAIN` に設定済み。ビルド時に `dist/CNAME` が自動生成される。
GitHub 側は **Settings → Pages → Custom domain** に `ai-oni.com` を設定する。

## ディレクトリ

```
aioni/            サイト生成本体（build.py / seo.py / business.py / config.py / topics.py）
  collectors/     収集・本文取得・翻訳
  templates/      Jinja2 テンプレート
content/articles/ 記事の Markdown（<slug>.ja.md）
data/             収集データ（news.json / papers.json / translations.json）
static/           CSS・JS・画像
tools/            デプロイと点検のスクリプト
dist/             生成物（コミットしない）
```

## AI検索（AEO）まわり

| 項目 | 実装 |
|---|---|
| 構造化データ | 全ページに JSON-LD。`Organization` / `WebSite` / `BreadcrumbList`、記事は `Article`、集約ニュースは解説があれば `NewsArticle`（`isBasedOn` で元記事を明示）、無ければ `WebPage` |
| llms.txt | サイト構造と記事一覧をAI向けに提供。`## Identity` 節で**同名の別サービスとの区別**を明記 |
| robots.txt | 検索エンジンとAIクローラの双方を明示的に許可 |
| IndexNow | デプロイのたびに全URLを通知 |
| 可視性チェッカー | トップに設置。会社名を入れるとAIがその企業をどう認識しているかをその場で測る（Vercel の `/api/diagnose`） |

## 出典・データ提供元

見出しと要約は配信元へリンクし、著作権は各社に帰属する。データ提供元は
OpenAI / Google DeepMind / Google AI / Hugging Face / MIT Technology Review /
TechCrunch / The Verge / VentureBeat / Ars Technica / ITmedia AI+ / AINOW /
Zenn / Qiita / Publickey / ASCII.jp / arXiv。

運営: 株式会社TOE（福岡市中央区） <https://gtoe.info/>

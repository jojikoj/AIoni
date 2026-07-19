# AIの鬼 🛰

**宇宙開発を、世界とつなぐ。** — 国内外の宇宙開発ニュース・打ち上げ予定・研究動向を集約し、日本語と英語で発信する静的サイト。

🌐 <https://uchuchu.tech>

> **運用中のAPI従量課金はゼロ。** データ収集はすべて無料の公開API/RSS、翻訳はローカルの Claude Code、公開は GitHub Pages。

---

## 何ができるか

| ページ | 内容 | 規模 | データ元 |
|---|---|---|---|
| ニュース | 国内外の宇宙開発ニュース（ソース別ページ・ページ分割） | 最大600件 | 19ソース（sorae / SpaceNews / NASA / ESA / Space.com / Ars Technica / Spaceflight News API ほか） |
| 打ち上げ | 世界のロケット打ち上げ予定＋実績（ライブカウントダウン） | 最大200件 | Launch Library 2 (The Space Devs) |
| 研究動向 | 宇宙工学・惑星科学・宇宙物理の最新プレプリント | 最大250件 | arXiv API |
| 特集 | 手書きの解説記事（Markdown） | 随時 | `content/articles/` |

### 記事を積み上げる仕組み

- **アーカイブ蓄積**: 収集のたびに上書きせず、既存データへ新着を統合する（URL/IDで重複排除）。
  日を追うごとに記事数が増え、上限（`NEWS_LIMIT` など）まで積み上がる。
- **翻訳キャッシュ**: 訳した記事は `data/translations.json` にURLキーで保存し、
  次回以降は再翻訳しない。これがないと毎回数百件を訳し直すことになる。
- **ページ分割**: 一覧は1ページ30件（`PAGE_SIZE`）。`news/`, `news/2/`, ... の実ページとして出力。
- **ソース別ページ**: `news/source/<id>/` を実ページとして生成。
  ページ分割後もソース絞り込みが正しく機能し、検索インデックス対象も増える。
- **話題フィルタ**: 総合メディア（ギズモード等）は宇宙関連キーワードに一致した記事だけ採用する。

### 言語まわりの仕様

- 日本語版は `/`、英語版は `/en/` に生成される。
- **ブラウザの言語で自動振り分け**。日本語ブラウザは日本語版、それ以外は英語版へ。
  ヘッダーの `JA / EN` で手動選択すると、その選択が以後優先される。
- **英語ソースの記事は日本語に翻訳して掲載**する（「自動翻訳」バッジ付き）。
- 日本語ソースの記事は英語版には載せない。日→英の機械翻訳は品質が公開に耐えないため。

---

## セットアップ

```bash
pip install -r requirements.txt
```

翻訳を有効にするには、ローカルに [Claude Code](https://claude.com/claude-code) が入っていれば自動で使われます（`claude` コマンド）。

## 使い方

```bash
./run.sh all        # 収集 → 生成 → プレビュー (http://localhost:8765)
./run.sh collect    # データ収集＋翻訳のみ
./run.sh build      # サイト生成のみ
./run.sh serve      # 生成してプレビュー
./run.sh publish    # 収集 → 生成 → commit & push（GitHub Pages が自動更新）
```

---

## 更新の流れ

```
[ローカル Mac]                              [GitHub]
 collect  ── 無料の公開API/RSSから収集
    │
 translate ── claude CLI で英→日翻訳（従量課金なし）
    │
 build    ── dist/ に日英サイトを生成
    │
 git push ────────────────────────────────▶ Actions がビルド＆Pages公開
                                              → https://uchuchu.tech
```

収集と翻訳を**ローカルで行う**のがこの構成の要。GitHub Actions 上では `claude` が使えないため、
Actions は「コミット済みの `data/*.json` からサイトを生成して公開する」だけを担当する。

### 定期更新（任意）

Mac の cron に登録すれば自動で更新できる。

```cron
# 毎日 7:00 と 19:00 に収集して公開
0 7,19 * * * cd /Users/kojimajouji/AIの鬼 && ./run.sh publish >> /tmp/uchuchu.log 2>&1
```

---

## 独自ドメイン（uchuchu.tech）

`uchuchu/config.py` の `SITE_DOMAIN` に設定済み。ビルド時に `dist/CNAME` が自動生成される。

DNS（ムームードメイン）側は以下を設定する。

| サブドメイン | 種別 | 内容 |
|---|---|---|
| （空欄） | A | 185.199.108.153 |
| （空欄） | A | 185.199.109.153 |
| （空欄） | A | 185.199.110.153 |
| （空欄） | A | 185.199.111.153 |
| www | CNAME | jojikoj.github.io |

GitHub 側は **Settings → Pages → Custom domain** に `uchuchu.tech` を入力し、
DNSチェック通過後に **Enforce HTTPS** を有効化する。

---

## 構成

```
uchuchu/
  config.py              サイト設定・データソース定義（ソース追加はここ）
  i18n.py                UI文言の日英辞書
  build.py               静的サイトジェネレータ
  collectors/
    sources.py           各ソースの取得ロジック
    collect_all.py       収集オーケストレーター（フェイルソフト）
    translate.py         翻訳（claude CLI → argostranslate → 原文の3段）
  templates/             Jinja2テンプレート
content/articles/        特集記事（Markdown）
static/                  CSS / JS / 画像
data/                    収集結果JSON（コミット対象）
dist/                    生成物（gitignore）
```

---

## 記事を追加する

`content/articles/` に `<スラッグ>.ja.md` と `<スラッグ>.en.md` を置くだけ。

```markdown
---
title: 記事タイトル
excerpt: 一覧に出る要約文
tag: 特集
author: AIの鬼 編集部
date: 2026-07-15
order: 1
---

本文をMarkdownで書く。
```

`order` が小さいほど上に出る。日英どちらか一方だけでもよい（その言語版にのみ表示）。

## ニュースソースを追加する

`uchuchu/config.py` の `NEWS_SOURCES` に追記する。

```python
{"id": "myfeed", "name": "表示名", "lang": "ja",
 "url": "https://example.com/feed", "type": "rss"},
```

取得に失敗したソースは自動でスキップされ、他のソースの収集は継続する。

---

## 翻訳バックエンド

| 優先 | エンジン | 品質 | 備考 |
|---|---|---|---|
| 1 | `claude` CLI | 高（公開レベル） | ローカルのClaude Codeを使用。従量課金なし |
| 2 | argostranslate | 低〜中 | 完全オフライン。`pip install argostranslate`＋`python3 -m uchuchu.collectors.translate --install` |
| 3 | なし | — | 原文のまま掲載。サイトは常に動く |

現在のバックエンドは次で確認できる。

```bash
python3 -m uchuchu.collectors.translate
```

---

## SEO / AEO（AI検索）対策

| 施策 | 内容 |
|---|---|
| 構造化データ | 全ページに JSON-LD。`WebSite`（主題エンティティをWikidataに紐付け）/ `Organization` / `BreadcrumbList`。打ち上げは `Event`、自作記事は `Article`、集約コンテンツは `ItemList` |
| **FAQPage** | `/faq/` に日英各9問のQ&Aを構造化データ付きで掲載。回答エンジンが最も引用しやすい形式 |
| **サイト内検索** | `/search/` で全コンテンツを横断検索。静的JSONインデックス方式でサーバー不要。`SearchAction` も出力 |
| llms.txt | `/llms.txt` にサイト構造・出典・翻訳の但し書きを記載（AI検索の新標準） |
| **llms-full.txt** | `/llms-full.txt` に自作記事とFAQの全文を提供。集約した外部記事は著作権上あえて含めない |
| robots.txt | GPTBot / ClaudeBot / PerplexityBot / Google-Extended など主要AIクローラ18種を明示的に許可 |
| RSS | `/feed.xml`（日本語）と `/en/feed.xml`（英語） |
| sitemap.xml | 実際に生成した全ページ（分割ページ・ソース別ページ含む）に `lastmod`・`priority`・hreflang相互リンク |
| 多言語 | `hreflang` と `x-default`、ブラウザ言語による自動振り分け |
| OGP | 1200×630 のSNS共有カードを同梱 |

構造化データの方針として、**外部から集約した記事を自作記事に見せかけない**。
集約コンテンツは `ItemList` として「リンク集」であることを明示し、`Article` は自作記事にのみ使う。
`llms-full.txt` に外部記事本文を含めないのも同じ理由。

---|---|
| 構造化データ | 全ページに JSON-LD（WebSite / Organization / BreadcrumbList）。打ち上げは `Event`、自作記事は `Article`、集約コンテンツは `ItemList` として出力 |
| llms.txt | `/llms.txt` にAI向けのサイト構造・出典・翻訳の但し書きを記載（AI検索の新標準） |
| robots.txt | 検索エンジンに加え GPTBot / ClaudeBot / PerplexityBot / Google-Extended など主要AIクローラを明示的に許可 |
| RSS | `/feed.xml`（日本語）と `/en/feed.xml`（英語） |
| sitemap.xml | `lastmod`・`priority`・hreflang相互リンク付き |
| 多言語 | `hreflang` と `x-default`、ブラウザ言語による自動振り分け |
| OGP | 1200×630 のSNS共有カードを同梱（`static/img/ogp.png`、元HTMLも同梱） |

構造化データの方針として、**外部から集約した記事を自作記事に見せかけない**。
集約コンテンツは `ItemList` として「リンク集」であることを明示し、`Article` は自作記事にのみ使う。

---

## データ元へのクレジット

- [Spaceflight News API](https://spaceflightnewsapi.net/)
- [The Space Devs / Launch Library 2](https://thespacedevs.com/)
- [arXiv](https://arxiv.org/)
- [NASA](https://www.nasa.gov/) / [ESA](https://www.esa.int/) / [sorae](https://sorae.info/) / [アストロアーツ](https://www.astroarts.co.jp/)

各記事の著作権は元の発信者に帰属します。本サイトは見出し・要約・リンクによる集約と、
出典を明示した上での翻訳掲載を行っています。

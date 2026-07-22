"""AIの鬼 グローバル設定。

サイト全体のメタ情報・データソース・言語設定を一元管理する。
運用中に外部AI APIを一切叩かない設計（収集はすべて無料の公開API/RSS）。
"""
from __future__ import annotations

import os
from pathlib import Path

# --- パス ---------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONTENT_DIR = ROOT / "content"
ARTICLES_DIR = CONTENT_DIR / "articles"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR = ROOT / "static"
DIST_DIR = ROOT / "dist"

# --- サイト情報 ---------------------------------------------------------
SITE_NAME = "AIの鬼"
SITE_TAGLINE = {
    "ja": "AI実践・実測ラボ",
}
SITE_DESCRIPTION = {
    "ja": "株式会社TOEが自社の業務でAIを動かした記録と、ChatGPT・Perplexity・AI Overviews を"
          "実際に測った結果を公開する、中小企業のためのAI実践・実測ラボ。"
          "うまくいった話も失敗も、数字のまま。最新の研究・調査は中小企業向けに読み解き、"
          "国内外のニュースも選別して届けます。経営者・情報システム担当向け。",
}

# --- アクセス解析 -------------------------------------------------------
# GA4 の測定ID（G-XXXXXXXXXX）。空のままなら計測タグを出力しない。
# 環境変数 GA4_ID でも上書きできる（本番だけ計測する場合に使う）。
# 値を入れてビルドすれば、全ページの <head> に gtag が入る。
# 2026-07-19 設定。GA4プロパティ「AIの鬼」のウェブストリーム。
# 環境変数 GA4_ID があればそちらが優先（検証用に空にして計測を止められる）。
# cron には環境変数が渡らないため、既定値をここに直接持たせる。
GA4_MEASUREMENT_ID = os.environ.get("GA4_ID", "G-SNQPGVMWWW")

# ヒーロー帯のコピー（2026-07-19 決定）。
# 「鬼」を擬人化した編集者として置き、読者の状態（情報が多すぎて追えない）から入る。
# 主張を述べるのではなく、このサイトが何をしているかを言う。
# 1要素ずつ改行して表示する。テンプレート側で <br> を組むので、
# ここに HTML を書かない（自動エスケープされるため）。
HERO_COPY = [
    "語るより、動かす",
    "鬼の仕事、隠さず報告",
]
HERO_SUB = ("株式会社TOEが自社の業務でAIを動かした記録と、"
            "ChatGPT・Perplexity・AI Overviews を実際に測った数字。"
            "成果も失敗も、そのまま出す。")
# 独自ドメイン。dist/CNAME に書き出され、GitHub Pages がこのドメインで配信する。
# 空文字にすると CNAME を出力しない（github.io のURLで公開）。
# 2026-07-19 取得（ムームードメイン）。ムームーDNSのカスタム設定で
# GitHub Pages の A 4件 ＋ www CNAME を登録済み。
SITE_DOMAIN = "ai-oni.com"

# 公開URL。デプロイ時に環境変数 SITE_BASE_URL で上書き可。
SITE_BASE_URL = "https://ai-oni.com"

# --- 問い合わせ ---------------------------------------------------------
# 静的サイトのためサーバー側フォーム処理を持てない。
# mailto: で件名・本文を事前入力し、送信の手間を最小化する。
# 問い合わせはフォーム(GAS)で受けるため、サイト上にアドレスを出さない。
# 出すとスパム収集ボットに拾われ、迷惑メールが増える。
# 内部処理でも使わない（宛先はGAS側の NOTIFY_TO で管理する）。
CONTACT_EMAIL = ""

# Googleフォームの埋め込みURL。
# 設定すると問い合わせページにフォームを埋め込む。
# 空のあいだは、メーラーを開く自前フォームにフォールバックする。
# 取得方法: Googleフォーム編集画面 → 送信 → < > タブ → src="..." の中身
GOOGLE_FORM_URL = ""

# フォーム送信先。FormSubmit を使うと、アカウント登録もAPIキーも不要で
# 静的サイトのままフォーム送信を受け取れる。
# 初回送信時に CONTACT_EMAIL 宛へ有効化リンクが届き、一度クリックすれば以降は直接届く。
# 空にすると mailto フォールバック（訪問者のメーラーが開く）に戻る。
# コンテンツ部 共通GAS（全メディアの問い合わせを1つのデプロイで受ける）。
# 第三者サービスを経由せず、自社のGoogleアカウント内で完結する。
# 実体: claude_AIR/TOEcompany/コンテンツ部/共通/gas/受付.gs
# 2026-07-19 修正: 別デプロイのURLを指していたため、共通GASの本番URLへ統一。
# 共通GAS = コンテンツ部/共通/gas/受付.gs（バージョン2・アクセス「全員」）
FORM_ENDPOINT = "https://script.google.com/macros/s/AKfycbxRrZrhqiFlm3g0EcJl2pBVFowFrOMglLSWw_9FvalF532vj6xBTtnVALDQOcM2jl5NRg/exec"
GOOGLE_FORM_HEIGHT = 1200
COMPANY_NAME = "株式会社TOE"
COMPANY_URL = "https://gtoe.info/"

# 運営会社ページに載せる情報。
# メディアの信頼性（E-E-A-T）は「誰が運営しているか」が明確なほど高く評価される。
# 連絡先は載せない — 問い合わせはフォームで受けるため。
COMPANY_PROFILE = [
    ("社号", "株式会社TOE（ティーオーイー）"),
    ("代表取締役社長", "小嶋 譲司"),
    ("福岡本社", "〒810-0004 福岡県福岡市中央区渡辺通1丁目9-3 1丁目ビル203号"),
    ("東京オフィス", "〒114-0001 東京都北区東十条1丁目12-7 303号"),
    ("大阪出張所", "〒537-0012 大阪市東成区大今里2丁目9-5-615"),
    ("事業内容", "Web制作／AI開発"),
    ("公式サイト", "https://gtoe.info/"),
]

# 日本語のみ。読者は国内の経営者・情シスで、英語版を出す必要がない。
# （UchUchU は宇宙産業が国際市場のため ja/en 二言語だった）
# --- トップの実績表示 ---------------------------------------------------
# 「本当にAIを使っている会社だ」と伝えるための数字。
# **実際に確認できる事実だけを使う。** 盛った数字を1つ入れた時点で、
# 実践記録全体の信頼が消える。
#
# 根拠:
#   27本  … crontab -l と orchestrator/jobs.yaml の実カウント
#   8:00  … cron の `0 8 * * 1-5`（当初 7:47 としていたが実設定は 8:00）
#   2媒体 … UchUchU（uchuchu.tech）／補助金の鬼（hojokin.website）
#   0円   … 収集=無料RSS、翻訳/要約=ローカルCLI、配信=GitHub Pages
PROOF_STATS = [
    {"n": "27", "label": "AIで自動化した社内業務"},
    {"n": "毎朝8:00", "label": "AI秘書が自動でブリーフィング"},
    {"n": "2媒体", "label": "収集・生成・配信を無人で運用"},
    {"n": "0円", "label": "運用中のAI API課金"},
]


# --- 記事カテゴリ -------------------------------------------------------
# 自社記事（content/articles/*.md）の分類。フロントマターの tag と対応する。
#
# 集約ニュースではなく、この自社記事群がサイトの主役。
# 「ニュースが多いサイト」ではなく「本当にAIを使っている会社」と伝わることを優先する。
ARTICLE_CATEGORIES = [
    {
        "id": "jissen",
        "tag": "AI実践室",
        "name": "AI実践室",
        "desc": "TOEが自社の業務でAIをどう動かしているかの一次記録。処理件数・所要時間・失敗件数をそのまま載せる。",
        "eyebrow": "実践",
    },
    {
        "id": "kansoku",
        "tag": "AI検索観測所",
        "name": "AI検索観測所",
        "desc": "ChatGPT・Perplexity・AI Overviews に実際に質問を投げ、どこが引用されるかを測った結果。意見ではなく数字を置く。",
        "eyebrow": "実測",
    },
    {
        "id": "shippai",
        "tag": "失敗の鬼",
        "name": "失敗の鬼",
        "desc": "AI導入・自動化で実際に起きた失敗。うまくいかなかったことも公開する。",
        "eyebrow": "失敗",
    },
    {
        "id": "shigoto",
        "tag": "AI仕事術",
        "name": "AI仕事術",
        "desc": "中小企業がAIを実務に入れるための実践ガイド。最初の一歩・費用・ツール選び。",
        "eyebrow": "実務",
    },
    {
        "id": "kaisetsu",
        "tag": "AI解体新書",
        "name": "AI解体新書",
        "desc": "AIの最新研究・調査・企業事例を、中小企業向けに読み解く。一次資料に当たって数字を確かめる。",
        "eyebrow": "解説",
    },
    {
        "id": "weekly",
        "tag": "今週のAI",
        "name": "今週のAI",
        "desc": "集めた大量のニュースから、中小企業が知る必要のあるものだけを選ぶ。",
        "eyebrow": "選別",
    },
]

CATEGORY_BY_TAG = {c["tag"]: c for c in ARTICLE_CATEGORIES}


LANGS = ["ja"]
DEFAULT_LANG = "ja"

# --- データソース -------------------------------------------------------
# RSSニュースソース。lang は原文の言語。英語ソースは日本語版でも表示され、
# 翻訳済み（title_ja）があればそちらを出す（build.py の prepare_news）。
# 個別ソースが落ちても収集全体は継続する（フェイルソフト）。
#
# "topic_filter": True を付けたソースは AI 以外の記事も配信するため、
# AI関連キーワードに一致した記事だけを採用する（sources.py の is_ai_related）。
#
# 2026-07-19 に全件生存確認済み。Ledge.ai と Anthropic 公式は RSS が無く不採用。
NEWS_SOURCES = [
    # --- 日本語ソース（実務向け・主軸）---
    # 読者は国内の経営者・情シス。日本語オリジナル記事の比率を重視する。
    {"id": "itmedia_ai", "name": "ITmedia AI+", "lang": "ja",
     "url": "https://rss.itmedia.co.jp/rss/2.0/aiplus.xml", "type": "rss"},
    {"id": "ainow", "name": "AINOW", "lang": "ja",
     "url": "https://ainow.ai/feed/", "type": "rss"},
    {"id": "zenn_ai", "name": "Zenn AI", "lang": "ja",
     "url": "https://zenn.dev/topics/ai/feed", "type": "rss"},
    {"id": "qiita_ai", "name": "Qiita AI", "lang": "ja",
     "url": "https://qiita.com/tags/ai/feed", "type": "rss"},
    # 総合IT系（AI関連記事のみ採用）
    {"id": "publickey", "name": "Publickey", "lang": "ja",
     "url": "https://www.publickey1.jp/atom.xml", "type": "rss", "topic_filter": True},
    {"id": "ascii", "name": "ASCII.jp", "lang": "ja",
     "url": "https://ascii.jp/rss.xml", "type": "rss", "topic_filter": True},

    # --- 英語ソース（開発元の一次情報）---
    {"id": "openai", "name": "OpenAI", "lang": "en",
     "url": "https://openai.com/news/rss.xml", "type": "rss"},
    {"id": "deepmind", "name": "Google DeepMind", "lang": "en",
     "url": "https://deepmind.google/blog/rss.xml", "type": "rss"},
    {"id": "googleai", "name": "Google AI", "lang": "en",
     "url": "https://blog.google/technology/ai/rss/", "type": "rss"},
    {"id": "huggingface", "name": "Hugging Face", "lang": "en",
     "url": "https://huggingface.co/blog/feed.xml", "type": "rss"},

    # --- 英語ソース（専門メディア）---
    {"id": "mit_tr", "name": "MIT Technology Review", "lang": "en",
     "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
     "type": "rss"},
    {"id": "techcrunch_ai", "name": "TechCrunch AI", "lang": "en",
     "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "type": "rss"},
    {"id": "verge_ai", "name": "The Verge AI", "lang": "en",
     "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
     "type": "rss"},
    {"id": "venturebeat_ai", "name": "VentureBeat AI", "lang": "en",
     "url": "https://venturebeat.com/category/ai/feed/", "type": "rss"},
    {"id": "arstechnica_ai", "name": "Ars Technica AI", "lang": "en",
     "url": "https://arstechnica.com/ai/feed/", "type": "rss"},
]

# 論文（arXiv）— AI関連カテゴリ（人工知能・自然言語処理・機械学習・画像認識）
ARXIV_QUERY_URL = (
    "http://export.arxiv.org/api/query?"
    "search_query=cat:cs.AI+OR+cat:cs.CL+OR+cat:cs.LG+OR+cat:cs.CV"
    "&sortBy=submittedDate&sortOrder=descending&max_results=250"
)

# 保持する最大件数（アーカイブ蓄積の上限）
NEWS_LIMIT = 600
PAPERS_LIMIT = 250

# 一覧ページの1ページあたり表示件数
PAGE_SIZE = 30

# ネットワーク
HTTP_TIMEOUT = 25
USER_AGENT = "AIoni/1.0 (+https://github.com/; AI news aggregator)"

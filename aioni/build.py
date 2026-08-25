"""静的サイトジェネレータ。

data/*.json（収集結果）+ content/articles/*.md（手書き記事）を読み、
日本語の静的サイトを dist/ に生成する。外部通信・AI APIは一切なし。

出力構成:
    dist/index.html            日本語トップ
    dist/news/ papers/ articles/ jissen/ shippai/ weekly/ aeo/ shigoto/
    dist/articles/<slug>/
    dist/static/  sitemap.xml robots.txt 404.html .nojekyll

実行:
    python -m aioni.build
"""
from __future__ import annotations

import hashlib
import html as html_mod
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import business, config, indexnow, seo, topics
from .i18n import t as _t

sys.path.insert(0, str(Path.home() / "claude_AIR/TOEcompany/メディア事業部/共通/運用"))
try:
    import neon  # noqa: E402
except ImportError:
    neon = None  # 共通運用フォルダが無い実行機（あり得る）。ファイルのみで動く


# --- データ読み込み -----------------------------------------------------
#
# ⚠️ 2026-08-24、サイトの読み出し先をファイルからNeon(DB)へ寄せ始めた。
#    正本は今もファイル（data/*.json・content/articles/*.ja.md）——
#    日次の収集・生成・trim_news.py はすべてファイルに書く。DBは「ビルドが
#    読みに行く先」を切り替えただけで、書き込み側の構造は変えていない。
#
#    **DBが読めない・空・件数がおかしいときは、必ずファイルに戻る。**
#    ここで無言に倒れると「ビルドは通ったが中身が古い/空」という、
#    このプロジェクトで何度も踏んだ壊れ方を再現する。フォールバックしたら
#    必ず1行ログに出す。
def _load_json(name: str) -> dict:
    path = config.DATA_DIR / name
    if not path.exists():
        return {"items": [], "generated_at": None}
    return json.loads(path.read_text(encoding="utf-8"))


# ニュース1件が持つべき最低限の件数。DBから拾えた件数がこれを大きく下回るなら
# 「接続はできたが中身がおかしい」可能性が高いのでファイルへフォールバックする。
# ファイル側の件数と比較するのではなく固定値にしているのは、この関数の中で
# ファイルを読まずに判定したいため（DBが正常な限りファイルI/Oを増やさない）。
_NEWS_SANITY_MIN = 100


def load_news() -> list[dict]:
    """news.json 相当を返す。Neonが読めればそちら優先、駄目ならファイル。

    DB側の1行は `raw`（body_src を除く元の1件）をそのまま持っている。
    ここで返す形は、ファイルからロードした場合と完全に同じ辞書のリストになる
    ——呼び出し側（このモジュールの残り全部）はどちらから来たか意識しない。
    """
    if neon is not None:
        # seq（news.json での元の並び順）で確定させる。published だけだと
        # 同時刻の記事のタイブレークがPostgres任せになり、ファイル読みと
        # 順序が変わってしまう（一覧の並び・重複記事の代表選びが変わる実害あり）。
        rows = neon.fetch_or_none(
            "select raw from aioni.news where raw is not null order by seq nulls last")
        if rows is not None and len(rows) >= _NEWS_SANITY_MIN:
            return [r[0] for r in rows]
        if rows is not None:
            print(f"⚠️ Neonのニュースが{len(rows)}件しかありません"
                  f"（{_NEWS_SANITY_MIN}件未満）。ファイルにフォールバックします", file=sys.stderr)
    return _load_json("news.json").get("items", [])


# --- 日付整形 -----------------------------------------------------------
_EN_MONTHS = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def fmt_date(iso: str | None, lang: str, with_time: bool = False) -> str | None:
    dt = _parse_iso(iso)
    if dt is None:
        return None
    if lang == "ja":
        base = f"{dt.year}年{dt.month}月{dt.day}日"
        if with_time:
            base += f" {dt.hour:02d}:{dt.minute:02d} UTC"
        return base
    base = f"{_EN_MONTHS[dt.month]} {dt.day}, {dt.year}"
    if with_time:
        base += f" {dt.hour:02d}:{dt.minute:02d} UTC"
    return base


_JA_WDAY = ["月", "火", "水", "木", "金", "土", "日"]
_EN_WDAY = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def fmt_date_short(iso: str | None, lang: str) -> str | None:
    """一覧用の短い絶対表記。曜日を入れる。

    「2時間前」のような相対表記は使わない。AIは動きが速く、
    いつの発表かを日付で押さえられることが情報価値になるため。
    """
    dt = _parse_iso(iso)
    if dt is None:
        return None
    # メディアで一般的な YYYY.MM.DD 表記。桁が揃い一覧で読みやすい。
    return f"{dt.year}.{dt.month:02d}.{dt.day:02d}"


def countdown_label(iso: str | None, now: datetime, lang: str) -> str | None:
    dt = _parse_iso(iso)
    if dt is None:
        return None
    delta = dt - now
    secs = int(delta.total_seconds())
    if secs <= 0:
        return "T-0" if lang == "en" else "まもなく"
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    if lang == "ja":
        if days > 0:
            return f"T-{days}日 {hours}時間"
        if hours > 0:
            return f"T-{hours}時間 {mins}分"
        return f"T-{mins}分"
    if days > 0:
        return f"T-{days}d {hours}h"
    if hours > 0:
        return f"T-{hours}h {mins}m"
    return f"T-{mins}m"


_STATUS_CLASS = {
    "go": "go", "success": "success", "tbd": "tbd", "tbc": "tbd",
    "hold": "hold", "failure": "hold", "partial failure": "hold",
    "in flight": "go",
}


# 画像のない記事に使うイメージ写真。主題に応じて出し分ける。
# 元記事の写真ではないため、テンプレート側で「イメージ」と明示する。
#
# 同じトピックの記事が一覧に並ぶと同じ写真が連続してしまうため、
# トピックごとに3枚用意し、記事URLのハッシュで振り分ける。
# ランダムではなくハッシュにするのは、再ビルドしても同じ記事に
# 同じ写真が付き、差分が無駄に膨らまないようにするため。
_FALLBACK_VARIANTS = ("a", "b", "c")

_FALLBACK_BY_TOPIC = {
    "models": "fallback-model",
    "tools": "fallback-tool",
    "dev": "fallback-dev",
    "business": "fallback-business",
    "policy": "fallback-policy",
    "research": "fallback-research",
    "infra": "fallback-infra",
    "japan": "fallback-japan",
}


# 集約ニュースで画像が無いものに割り当てる図解SVG。
# 収集600件のうち画像を持つのは85件（14%）だけ。残りに Flux 写真24枚を
# 配ると同じ写真が1枚あたり20回以上出て、量産サイトに見える。
# SVGは1枚1.5KBで144枚あるため、同じ絵が並びにくい。
# → tools/gen_news_svg.py で生成。オリジナル記事のヒーローは Flux 写真のまま。
_NEWS_SVG_VARIANTS = 16


def _fallback_image(topics: list[str], seed: str = "") -> str:
    """ニュース用の図解SVGを1枚選ぶ（決定的）。"""
    topic = "default"
    for t in topics:
        if t in _FALLBACK_BY_TOPIC:
            topic = t
            break
    h = hashlib.sha1(seed.encode("utf-8")).hexdigest()
    v = int(h[:8], 16) % _NEWS_SVG_VARIANTS
    return f"news-{topic}-{v:02d}.svg"


# 記事カテゴリ → ニュース用トピック（イメージ写真の使い回しに使う）
# コーナー一覧の <title>。コーナー名（造語）だけでは検索窓に打たれないので、
# 読者が実際に打つ語を後ろに足す。h1・パンくず・ナビはコーナー名のまま。
_CATEGORY_SEARCH_TITLE = {
    "jissen": "AI活用の実践記録 — AI実践室",
    "aeo": "AI検索対策（AEO）の実務 — AEO対策室",
    "shippai": "AI導入の失敗事例 — 失敗の鬼",
    "shigoto": "中小企業のAI活用ガイド — AI仕事術",
    "kaisetsu": "AI研究・調査の解説 — AI解体新書",
    "weekly": "今週のAIニュース — 今週のAI",
    "naka": "AIと働く日々の記録 — 中の鬼",
}

_ARTICLE_CAT_TO_TOPIC = {
    "jissen": "tools",
    "shippai": "policy",
    "weekly": "models",
    "aeo": "research",
    "shigoto": "tools",
    "kaisetsu": "research",
}


# --- データ整形 ---------------------------------------------------------
def prepare_news(raw: list[dict], lang: str) -> list[dict]:
    """その言語サイトに載せるニュースを選び、表示用に整形する。

    ja: 全ソース。英語ソースは日本語訳（title_ja/summary_ja）があればそれを使う。
    en: 英語ソースのみ。日→英の機械翻訳は品質が低く公開に耐えないため、
        日本語ソースは英語サイトには載せない。
    """
    out = []
    for it in raw:
        if lang == "en" and it.get("lang") != "en":
            continue
        it = dict(it)
        it["published_display"] = fmt_date(it.get("published"), lang)
        it["published_short"] = fmt_date_short(it.get("published"), lang)
        # 自動翻訳で表示しているかどうか（UIバッジ用）
        it["is_translated"] = bool(
            it.get("lang") != lang and it.get(f"title_{lang}")
        )
        # 主題分類（原文で判定する。訳文よりキーワードが安定するため）
        it["topics"] = topics.classify(
            it.get("title", ""), it.get("summary", ""))
        # 一覧に出す主題ラベル（多すぎると読みにくいので1つに絞る）
        it["topic_labels"] = [topics.name(x, lang) for x in it["topics"][:1]]
        # サイト内の記事ページ。外部リンクに直接飛ばすと読者が離脱し、
        # 回遊も問い合わせも起きないため、必ず自サイトを経由させる。
        it["slug"] = news_slug(it)
        it["display_title"] = it.get(f"title_{lang}") or it.get("title") or ""
        it["display_summary"] = it.get(f"summary_{lang}") or it.get("summary") or ""
        # 画像のない記事にはトピックに応じたイメージ写真をあてる。
        # グレーの空欄が並ぶと一覧の見栄えが崩れ、記事も読まれにくくなるため。
        if not it.get("image"):
            it["stock_image"] = _fallback_image(
                it.get("topics", []), it.get("url", "") or it.get("title", ""))
            it["image_is_stock"] = True
        out.append(it)
    return out


# 記事末バナーで「AI検索対策」を出す合図。
# これらに触れている記事の読者は、AIに自社が出てくるかを気にしている。
_AEO_HINTS = (
    "aeo", "ai検索", "ai overview", "aioverview", "chatgpt 検索",
    "perplexity", "生成エンジン最適化", "引用され", "可視性", "被引用",
)


def cta_kind(*texts: str, category: str = "") -> str:
    """記事末に出す相談バナーの種別を決める。

    2商材（AI検索対策 / AI社内導入）のどちらを出すかを記事の内容で選ぶ。
    AEO対策室の記事と、AI検索・AEOを扱った記事は前者。それ以外は
    本命の「AI社内導入」を出す。判定に迷うものは導入側に倒す——
    読者の大半は「自社にAIをどう入れるか」を調べに来ているため。
    """
    if category == "aeo":
        return "aeo"
    hay = " ".join(t or "" for t in texts).lower()
    return "aeo" if any(h in hay for h in _AEO_HINTS) else "dounyu"


def paper_arxiv_id(url: str) -> str:
    """https://arxiv.org/abs/2607.22535v1 → 2607.22535（読み解きの突き合わせ用）"""
    m = re.search(r"/abs/([0-9]+\.[0-9]+)", url or "")
    return m.group(1) if m else ""


def prepare_papers(raw: list[dict], lang: str, readings: dict | None = None) -> list[dict]:
    readings = readings or {}
    out = []
    for it in raw:
        it = dict(it)
        it["published_display"] = fmt_date(it.get("published"), lang)
        # 日本語の読み解きがある論文だけ、一覧から個別ページへ導線を出す。
        aid = paper_arxiv_id(it.get("url", ""))
        if aid and aid in readings:
            it["reading_slug"] = aid
            it["title_ja"] = readings[aid].get("title_ja", "")
        out.append(it)
    return out


# --- 記事(Markdown) ----------------------------------------------------
_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, m.group(2)


_ARTICLES_SANITY_MIN = 20


def _iter_article_sources(lang: str):
    """(slug, meta, body) を返す。Neonが読めればそちら優先、駄目ならファイル。

    Neon側の frontmatter 列は、記事mdの先頭ブロックを丸ごと保存したもの
    （tools/sync_neon.py の article_rows 参照）。ファイルから読んだときと
    同じ (meta, body) の形にして返すので、以降のパース・レンダリングは
    データの出どころを意識しない。
    """
    if lang == "ja" and neon is not None:
        # slug昇順で確定させる。ファイル読みは glob() が返すパスのソート順
        # （＝slugのアルファベット順）なので、DBもそれに合わせないと
        # 関連記事マッチングの並び依存で結果が変わる（2026-08-24 実データで発見。
        # 順序無指定だとPostgresは毎回の実行順を保証しない）。
        rows = neon.fetch_or_none(
            "select slug, frontmatter, body from aioni.articles "
            "where frontmatter is not null order by slug")
        if rows is not None and len(rows) >= _ARTICLES_SANITY_MIN:
            for slug, meta, body in rows:
                yield slug, meta, body or ""
            return
        if rows is not None:
            print(f"⚠️ Neonの記事が{len(rows)}件しかありません"
                  f"（{_ARTICLES_SANITY_MIN}件未満）。ファイルにフォールバックします", file=sys.stderr)

    if not config.ARTICLES_DIR.exists():
        return
    for path in sorted(config.ARTICLES_DIR.glob(f"*.{lang}.md")):
        slug = path.name[: -len(f".{lang}.md")]
        meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        yield slug, meta, body


def load_articles(lang: str) -> list[dict]:
    """記事の一覧を組み立てる。中身は Neon かファイルのどちらか（上を参照）。"""
    md = markdown.Markdown(extensions=["extra", "toc", "sane_lists"])
    articles = []
    for slug, meta, body in _iter_article_sources(lang):
        md.reset()
        html = md.convert(body)
        tag = meta.get("tag", "")
        cat = config.CATEGORY_BY_TAG.get(tag)
        # hero 指定が無い記事には、カテゴリに応じたイメージ写真を当てる。
        # 一覧でグレーの矩形が並ぶと、記事そのものが読まれなくなるため。
        hero = meta.get("hero", "")
        # 中の鬼は「とがった実写hero」を必ず持たせる運用。hero未指定でも
        # slugからファイル名を自動導出（画像はgen_flux_images.pyが生成）。
        if not hero and tag == "中の鬼":
            hero = f"article-{slug}.jpg"
        if not hero:
            hero = _fallback_image(
                [_ARTICLE_CAT_TO_TOPIC.get(cat["id"] if cat else "", "")], slug)
        # 本文から読了時間を出す。読む前に「これは長いのか」が分かる方が親切。
        text_len = len(re.sub(r"<[^>]+>", "", html))
        articles.append({
            "slug": slug,
            "title": meta.get("title", slug),
            # <title> と meta description は検索結果で切られる長さが決まって
            # いる。front matter に手で書いてあればそれを使い、無ければ丸める。
            # h1・記事リードは title / excerpt のまま（読者向けの全文）。
            "seo_title": (meta.get("seo_title", "")
                          or article_head_title(meta.get("title", slug))),
            "meta_desc": (meta.get("meta_desc", "")
                          or clip_description(meta.get("excerpt", ""))),
            "excerpt": meta.get("excerpt", ""),
            "tag": tag,
            "category": cat["id"] if cat else "",
            "category_name": cat["name"] if cat else tag,
            "category_eyebrow": cat["eyebrow"] if cat else "",
            "author": meta.get("author", ""),
            "hero": hero,
            # hero がファイル名だけならサイト内の画像として解決する
            "hero_is_local": bool(hero) and not hero.startswith("http"),
            "date": meta.get("date", ""),
            # 公開後に加筆したら front matter に updated: を足す。
            # 無ければ公開日と同じ＝一度も直していない、という意味になる。
            "updated": meta.get("updated", "") or meta.get("date", ""),
            "date_display": fmt_date(meta.get("date"), lang) if meta.get("date") else "",
            "order": int(meta.get("order", "100") or "100"),
            "chars": text_len,
            "read_min": max(1, round(text_len / 600)),
            "html": html,
        })
    # 公開予定日（front matter の date）が未来の記事は、その日が来るまで出さない。
    # プレイブックの「まとめて生成し、publishedAt で1日N本ずつ出す」運用。
    # 日次cron（tools/daily.sh）が毎日ビルドし直すので、日付が来た記事が
    # 自動的に一覧・sitemap・feed に現れる。人手の操作は要らない。
    today = datetime.now(timezone.utc).astimezone().date().isoformat()
    scheduled = [a for a in articles if a["date"] and a["date"] > today]
    if scheduled:
        print(f"  公開待ち {len(scheduled)}本（最短 {min(a['date'] for a in scheduled)}）")
    articles = [a for a in articles if not (a["date"] and a["date"] > today)]

    articles.sort(key=lambda a: (a["order"], a["date"]), reverse=False)
    return articles


def load_faq(lang: str) -> tuple[dict, list[dict]]:
    """content/faq.<lang>.md を読む。 "Q: ..." / "A: ..." の対を抽出する。"""
    path = config.CONTENT_DIR / f"faq.{lang}.md"
    if not path.exists():
        return {}, []
    meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
    faqs, q = [], None
    for line in body.splitlines():
        line = line.strip()
        if line.startswith("Q:"):
            q = line[2:].strip()
        elif line.startswith("A:") and q:
            faqs.append({"q": q, "a": line[2:].strip()})
            q = None
    return meta, faqs


def article_plain_text(html: str) -> str:
    """記事HTMLから素のテキストを取り出す（llms-full.txt 用）。"""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_mod.unescape(text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _clip(text: str, limit: int) -> str:
    """全角前提で limit 文字に丸める。文の途中で切れないよう句点で寄せる。"""
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    # 句点で終われるならそこまで（文として閉じる）。
    pos = cut.rfind("。")
    if pos >= limit // 2:
        return cut[: pos + 1]
    # 句点が無ければ読点で切り、続きがあることを「…」で示す。
    # 読点をそのまま残すと文が途中でぶら下がって見えるため落とす。
    pos = cut.rfind("、")
    if pos >= limit // 2:
        return cut[:pos] + "…"
    return cut.rstrip() + "…"


# ニュース個別ページのタイトル末尾に付ける識別句。
#
# なぜ付けるか（2026-07-30 実測）:
#   「kimi k3 使い方」で /news/zenn_ai-.../ が平均1.6位まで来ていたのに
#   10表示0クリックだった。このページの <title> が配信元(Zenn)の記事タイトルと
#   一字一句同じで、検索結果に同じ見出しが2つ並び、読者は原典を選んでいた。
#   同一タイトルをやめ、「ここを開くと何が追加で読めるか」を出す。
#
# 嘘は書かない。要約本文があるページと、配信元の紹介文しかないページで
# 書き分ける（後者に「実務への影響」と書くと中身と合わない）。
_NEWS_TAIL_BODY = "｜要点と実務への影響"
_NEWS_TAIL_LINK = "｜出典と、関連する実践記録"

# <title> に出せる長さの上限（全角）。
#
# なぜ要るか（2026-08-05 実測）: ニュース個別ページの <title> は
# 配信元のタイトルをそのまま使っていて、実測25件中5件が61〜114字だった。
# Google の検索結果は日本語で30字前後までしか出さないので、後ろに付けた
# 識別句（_NEWS_TAIL_*）もサイト名も一切表示されず、「原典と同じ見出しが
# 並ぶ」という _NEWS_TAIL_* で直したはずの状態に逆戻りしていた。
#
# 32字に丸めておけば、識別句の先頭までは表示に載る可能性が出る。
# h1（本文の見出し）は元の全文のままにする。長くても読者は困らないし、
# 原典の題を省略せず示す方が誠実なため、丸めるのは <title> だけにする。
_HEAD_TITLE_LIMIT = 32

# タイトルを切ってよい位置。配信元が付けた飾り（「【速報】」「｜◯◯新聞」
# 「 - Qiita」など）の境目で切ると、意味の切れ目で終わりやすい。
_TITLE_BREAKS = "｜│|【】〔〕［］—–-：:、，,。 　"


def head_title(title: str, limit: int = _HEAD_TITLE_LIMIT) -> str:
    """<title> 用にニュースの題を丸める。h1 や OGP には使わない。

    句点で閉じられないタイトル（ニュースの見出しはほぼこれ）を _clip に
    渡すと限界まで詰めて「…」を足すだけになるため、区切り記号を優先して
    意味の切れ目で終わらせる。
    """
    title = re.sub(r"\s+", " ", (title or "")).strip()
    if len(title) <= limit:
        return title
    cut = title[:limit]
    # 予算内で最も後ろの区切りを探す。短くなりすぎる位置は使わない。
    pos = max((cut.rfind(ch) for ch in _TITLE_BREAKS), default=-1)
    if pos >= limit // 2:
        return cut[:pos].rstrip(_TITLE_BREAKS)
    return cut.rstrip() + "…"


# 自社記事のタイトルは「問い？＋実測値の列挙」という型で書いている。
# 読み物としては正しいが、そのまま <title> に出すと実測226本中206本
# （88%）が32字を超え、検索結果では問いの途中で切れてサイト名も出ない。
# h1 は全文のまま残し、<title> だけを「問いの一文」で終わらせる。
#
# front matter に seo_title: があればそれを最優先で使う（手で決めた題）。
_TITLE_SENTENCE_END = "？?！!。"
# 「主題 — 副題」の副題を落とすための区切り。表記ゆれ（ダッシュ4種）と、
# 実測値を添える括弧「〜できるのか（正答率58.54%）」を全部拾う。
_TITLE_SUBTITLE_SEP = ["—", "―", "─", "－", "──", "——", " - ", " – ", "：",
                       "（", "("]
# 読点で切ったとき、末尾がこれだと文が途中に見える（「〜理由と」「〜構成と」）。
# 「か」は問いの終わりなので落とさない（「どう選ぶか」は残したい形）。
_TRAILING_PARTICLES = "とやがはもをにでへ、，・「（【"


def _trim_marks(s: str) -> str:
    """切り口の末尾から、記号と開き括弧だけを落とす。"""
    return s.rstrip().rstrip("、，・「（【 　-–—―:：")


def _trim_tail(s: str) -> str:
    """切り口の末尾から、文を途中に見せる字を落とす。

    数字の途中（「404」→「40」、「1,125回」→「1」）で終わるのが最悪なので、
    末尾が数字・カンマ・小数点のときは数字の並びごと落とす。
    """
    s = _trim_marks(s)
    while s and s[-1] in _TRAILING_PARTICLES:
        s = _trim_marks(s[:-1])
    if s and (s[-1].isdigit() or s[-1] in ",.，"):
        s = _trim_marks(re.sub(r"[\d,.，]+$", "", s))
        while s and s[-1] in _TRAILING_PARTICLES:
            s = _trim_marks(s[:-1])
    return s


def article_head_title(title: str, limit: int = 30) -> str:
    """自社記事の <title> 用に題を丸める。h1・OGP には使わない。

    ニュース用の head_title と分けているのは、切ってよい位置が違うため。
    自社記事の題は「主題 — 副題」か「〜のか？＋実測値」の型で書いてあり、
    副題や数値の列挙を落とせば主題だけが残る。文の途中で切る「…」は、
    どこにも切れ目が無いときの最後の手段。
    """
    title = re.sub(r"\s+", " ", (title or "")).strip()
    if len(title) <= limit:
        return title
    cands = []
    # 1) 副題を落とす（「主題 — 副題」）
    for sep in _TITLE_SUBTITLE_SEP:
        pos = title.find(sep)
        if pos > 0:
            # 副題の前は文として完結しているので、記号だけ落として助詞は残す
            cands.append(_trim_marks(title[:pos]))
    # 2) 問い・言い切りで終わる位置（複数あれば予算内で最も後ろ）
    for ch in _TITLE_SENTENCE_END:
        pos = title.rfind(ch, 0, limit + 1)
        if pos > 0:
            cands.append(title[:pos + 1])
    ok = [c for c in cands if 6 <= len(c) <= limit]
    if ok:
        return max(ok, key=len)
    # 3) 文の切れ目が無い。読点で切る（ここまで来ると主題が削れるので最後）
    pos = title.rfind("、", 0, limit + 1)
    if pos > 0:
        cut = _trim_tail(title[:pos])
        if len(cut) >= 6:
            return cut
    # 4) どこにも切れ目が無い。字数で切って末尾を整える。
    cut = _trim_tail(head_title(title, limit).rstrip("…"))
    return (cut + "…") if cut else title[:limit]


def clip_description(text: str, limit: int = 120) -> str:
    """meta description 用に要約を丸める。

    excerpt はページ本文のリードとしても出すので長さを持たせてある。
    そのまま description に流すと実測226本中174本が120字を超え、検索結果
    でもAIの引用でも末尾（多くの場合そこに但し書きがある）が落ちる。
    文の切れ目で止め、文が1つも収まらないときだけ「…」で丸める。
    """
    text = re.sub(r"\s+", " ", (text or "")).strip()
    if len(text) <= limit:
        return text
    out = ""
    for sentence in re.findall(r"[^。！？]*[。！？]|[^。！？]+$", text):
        if len(out) + len(sentence) > limit:
            break
        out += sentence
    if len(out) >= limit // 2:
        return out.strip()
    return head_title(text, limit).rstrip("…") + "…"

# 解説の2段落目が、生成プロンプトの見出しをそのまま書き出しにしていることがある。
# description に出すときだけ、この定型の前置きを外す（本文はそのまま残す）。
_LEAD_BOILERPLATE = re.compile(
    r"^(?:【?AIの鬼の視点】?(?:から見れば|から見ると|から言えば|では|とし(?:て)?は|は)?、?\s*"
    r"|ここが主役(?:だ|です)。?\s*)+")


def news_meta(item: dict, lang: str) -> tuple[str, str]:
    """ニュース個別ページの (タイトル末尾, meta description) を返す。

    description は以前 display_title の丸写しだった（build.py が
    page_description=display_title を渡していた）。検索結果でタイトルと
    同じ文が2度出るだけで、開く理由を1文字も伝えていなかった。
    自社で書いた要約の冒頭を出す形に変える。
    """
    title = item.get("display_title") or ""
    source = item.get("source") or ""
    body = (item.get("body_long") or "").strip()

    if body:
        # 検索結果に出すのは、1段落目ではなく2段落目。
        #
        # 生成プロンプト(tools/gen_news_summaries.py)は3段落構成を指定していて、
        #   1段落目 … 何が起きたのか（事実の言い直し）
        #   2段落目 … AIの鬼の視点 ← ここが主役
        #   3段落目 … 中小企業の実務にどう効くか
        # となっている。1段落目を description に出すと、通信社原稿と同じ文が
        # 並ぶだけで「このサイトを開く理由」が伝わらない。
        #
        # 2026-08-01 実測: 検索表示の71%(396回)をニュース個別ページが占めるのに
        # CTR は 2.02%。自社記事(4.35%)の半分以下だった。順位2.7位・4.8位でも
        # クリック0のページがあり、そのページの description は
        # 「中国のMoonshot AIが、フラッグシップモデルを発表した。総パラメータ数…」
        # という元記事の要約と区別のつかない文だった。
        # 本文には独自の視点が書かれているのに、検索結果には出ていなかった。
        # 2026-08-02 追記: 上の修正は3割に効いていなかった。
        # 解説445件の段落数を数えたところ、131件(29.4%)が「1段落」と判定され、
        # paras[1] が存在せず1段落目に落ちていた。内訳を切り分けると
        #   20件 … 段落の区切りが \n\n ではなく \n 単独だっただけ（中身は3段落）
        #  111件 … 本当に改行が1つも無い（生成が2〜4段落の指示に従っていない）
        # 前者はここで拾える。\n\n で割って1つしか出ないときだけ \n で割り直す
        # （最初から \n で割ると、1文の途中の改行まで段落扱いしてしまう）。
        paras = [x.strip() for x in body.split("\n\n") if x.strip()]
        if len(paras) < 2:
            paras = [x.strip() for x in body.split("\n") if x.strip()]
        lead = paras[1] if len(paras) >= 2 else (paras[0] if paras else body)
        # 生成プロンプトの見出し（「2. AIの鬼の視点」）を、そのまま本文の書き
        # 出しに持ち込んでいるものが8件あった。検索結果に
        # 「AIの鬼の視点では、ここが重要です。…」と出ると、読者に伝わるのは
        # 媒体の自称だけで、肝心の中身が110字の枠から押し出される。
        # 定型の前置きだけを外す（後続は普通の文になっている）。
        lead = _LEAD_BOILERPLATE.sub("", lead).lstrip("　 ")
        return _NEWS_TAIL_BODY, _clip(lead, 110)

    summary = (item.get("display_summary") or "").strip()
    if summary:
        return _NEWS_TAIL_LINK, _clip(f"{source}の記事より：{summary}", 110)

    return _NEWS_TAIL_LINK, _clip(
        f"{source}が配信した「{title}」の出典リンクと、"
        f"この話題に関連する株式会社TOEの実践・実測記録をまとめています。", 110)


# --- ニュースと自社記事の関連付け -------------------------------------
# ニュース個別ページの「この話題に関連する、TOEの実践・観測記録」は、
# 以前は related_pool を (idx*3) で機械的に輪切りしただけで、実際には
# 話題と無関係な記事が並んでいた（見出しの主張と中身が合っていない）。
# キーワードの重なりで実際に関連する記事を先に出す。AI APIは使わない。
#
# 日本語は形態素解析なしで扱うため、2文字の連続（バイグラム）で照合する。
# 「AIエージェント」と「エージェント」のような部分一致も拾える。
_TOKEN_ASCII = re.compile(r"[A-Za-z][A-Za-z0-9.+#-]{2,}")
# どの記事にも出るため、一致しても関連性の証拠にならない語
_STOPWORDS = {"ai", "the", "and", "for", "with", "から", "する", "した", "して",
              "ある", "いる", "こと", "ため", "よう", "れる", "られ", "です",
              "ます", "この", "その", "とい", "いう", "もの", "なる", "って"}


def _keyset(*texts: str) -> set[str]:
    """照合用のキー集合。ASCII語＋日本語バイグラム。"""
    keys: set[str] = set()
    for text in texts:
        if not text:
            continue
        low = text.lower()
        keys.update(m.group(0) for m in _TOKEN_ASCII.finditer(low))
        # 日本語部分のバイグラム（英数記号と空白は切れ目として扱う）
        for chunk in re.split(r"[\sA-Za-z0-9_.,;:!?()\[\]{}'\"/\\|<>+*=~`@#$%^&—–―…、。「」『』（）〈〉]+", text):
            if len(chunk) < 2:
                continue
            keys.update(chunk[i:i + 2] for i in range(len(chunk) - 1))
    return {k for k in keys if k not in _STOPWORDS and len(k) >= 2}


def relevance_ranked(news_item: dict, pool: list[dict], limit: int = 3,
                     min_score: int = 4) -> list[dict]:
    """ニュース1件に対して、関連度の高い自社記事を limit 本返す。

    min_score に届く記事が limit 本に足りなければ、残りは呼び出し側が
    埋める（無関係なものを「関連」として並べたくないため、ここでは
    水増ししない）。
    """
    nkeys = _keyset(news_item.get("display_title", ""),
                    news_item.get("title", ""),
                    (news_item.get("body_long") or "")[:600])
    if not nkeys:
        return []
    scored = []
    for a in pool:
        score = len(nkeys & a["_keys"])
        if score >= min_score:
            scored.append((score, a))
    # 同点は order の小さい（＝上位に置きたい）記事を優先
    scored.sort(key=lambda x: (-x[0], x[1].get("order", 100)))
    return [a for _, a in scored[:limit]]


def related_articles(article: dict, pool: list[dict], limit: int = 3,
                     min_score: int = 10) -> list[dict]:
    """記事1本に対して、関連度の高い他の記事を limit 本返す。

    2026-08-01 実測: 記事207本のうち204本が本文に他記事へのリンクを
    1本も持たず、記事詳細に関連記事の欄も無かった。ニュース側には
    関連記事があるのに記事側には無く、読み終えた人が次に読むものへ
    移動できない状態だった（週次レポートの「孤立132本」もこれが原因）。

    関連度の測り方はニュース側(relevance_ranked)と同じ。ただし
    足りないぶんを無関係な記事で埋めることはしない。関連していない
    ものを「関連記事」として並べると、読者の信頼と回遊の両方を失う。
    同じカテゴリの記事はわずかに優先する（読者の関心が続きやすい）。

    min_score=10 は実測で決めた。4 と 10 はどちらも 207本すべてに
    3本ずつ付き、12 まで上げると 11本が3本に届かなくなる。上位3本を
    採る設計なので閾値を上げても選ばれる記事は変わらないが、
    弱い関連しか無い記事で無理に3本並べるのを防げる分だけ 10 が良い。
    """
    keys = _keyset(article.get("title", ""), article.get("excerpt", ""))
    if not keys:
        return []
    scored = []
    for a in pool:
        if a["slug"] == article["slug"]:
            continue
        score = len(keys & a["_keys"])
        if a.get("category") and a.get("category") == article.get("category"):
            score += 1
        if score >= min_score:
            scored.append((score, a))
    scored.sort(key=lambda x: (-x[0], x[1].get("order", 100)))
    return [a for _, a in scored[:limit]]


def news_slug(item: dict) -> str:
    """ニュース1件の安定したURLスラッグ。

    元記事URLのハッシュを使う。タイトルは翻訳で変わりうるが
    URLは変わらないため、再ビルドしてもスラッグが安定する。
    """
    src = item.get("source_id") or "news"
    h = hashlib.sha1((item.get("url") or "").encode("utf-8")).hexdigest()[:10]
    return f"{src}-{h}"


# ヒーローのメインに向かない記事の特徴。
# 口語的な見出し、スポーツ・エンタメ寄りの話題、株価の値動きなど、
# 製造業向けB2Bメディアの「顔」として弱いものを後ろに回す。
_WEAK_TITLE = [
    "…", "!?", "！？", "ずりずり", "やばい", "すごい", "だった件", "してみた",
    "アニメ", "映画", "ドラマ", "ゲーム", "グッズ", "回顧", "振り返",
    "株価", "急落", "暴落", "ランキング",
]
# 逆に主役に据えたい主題（産業・技術・国内）
_STRONG_TOPIC = ("rocket", "satellite", "japan", "business")


def _featured_score(item: dict) -> int:
    """ヒーローのメイン適性を点数化する。高いほど主役向き。"""
    title = (item.get("display_title") or item.get("title") or "")
    score = 0
    if any(w in title for w in _WEAK_TITLE):
        score -= 5
    if len(title) < 14:            # 短すぎる見出しは大きく出すと間が持たない
        score -= 2
    for t in item.get("topics", []):
        if t in _STRONG_TOPIC:
            score += 2
    if item.get("lang") == "ja":   # 日本語ソースは訳のぎこちなさがない
        score += 2
    # 本文要約があるページは読み応えがある。
    # 2026-07-30 修正: item.get("body_ja") を見ていたが news.json のフィールドは
    # body_long で、この加点は一度も入っていなかった（445/600件が対象外扱い）。
    if item.get("body_long"):
        score += 3
    return score


def _order_featured(items: list[dict]) -> list[dict]:
    """新しさを保ちつつ、主役に向くものを先頭へ寄せる。

    直近の記事だけを対象に並べ替える。全体を点数順にすると
    古い記事が主役になり、媒体が更新されていないように見えるため。
    """
    head = items[:12]
    rest = items[12:]
    head.sort(key=lambda x: -_featured_score(x))
    return head + rest


# --- ページ分割 ---------------------------------------------------------
def _paginate(items: list, size: int) -> list[list]:
    """items を size 件ずつに分割する。空でも1ページは返す（空表示のため）。"""
    if not items:
        return [[]]
    return [items[i:i + size] for i in range(0, len(items), size)]


def _pagination_ctx(current: int, total: int) -> dict:
    """テンプレートに渡すページャ情報。リンクは現在ページからの相対パス。

    1ページ目は <base>/、2ページ目以降は <base>/<n>/ に出力される。
    したがって base のセグメント数に関係なく、
    1ページ目から見た n ページ目は "n/"、2ページ目以降から見た 1 ページ目は "../"。
    """
    if total <= 1:
        return {"total": 1}

    up = "" if current == 1 else "../"

    def href(p: int) -> str:
        return up if p == 1 else f"{up}{p}/"

    # 表示するページ番号（現在の前後2つ＋先頭・末尾）
    window = {1, total, current}
    for d in (-2, -1, 1, 2):
        if 1 <= current + d <= total:
            window.add(current + d)
    nums = sorted(window)
    entries = []
    prev = 0
    for n in nums:
        if prev and n - prev > 1:
            entries.append({"gap": True})
        entries.append({"num": n, "href": href(n), "current": n == current})
        prev = n
    return {
        "total": total, "current": current, "entries": entries,
        "prev": href(current - 1) if current > 1 else None,
        "next": href(current + 1) if current < total else None,
    }


# --- レンダリング -------------------------------------------------------
class Builder:
    @staticmethod
    def _asset_version() -> str:
        """CSS/JSの内容から短いハッシュを作る。

        ブラウザはCSSを長期キャッシュするため、更新してもURLが同じだと
        古いCSSが使われ続ける。内容が変わったときだけURLが変わるようにする。
        """
        import hashlib
        h = hashlib.sha256()
        for name in ("css/style.css", "js/main.js", "js/search.js", "js/contact-form.js"):
            p = config.STATIC_DIR / name
            if p.exists():
                h.update(p.read_bytes())
        return h.hexdigest()[:8]

    def __init__(self):
        self.env = Environment(
            loader=FileSystemLoader(str(config.TEMPLATES_DIR)),
            autoescape=select_autoescape(["html", "xml"]),
            trim_blocks=True, lstrip_blocks=True,
        )
        self.now = datetime.now(timezone.utc)
        self.build_time = self.now.strftime("%Y-%m-%d %H:%M UTC")
        self.asset_ver = self._asset_version()
        self.year = self.now.year
        self.base_url = os.environ.get("SITE_BASE_URL", config.SITE_BASE_URL).rstrip("/")
        self.news_raw = load_news()
        self.papers_raw = _load_json("papers.json").get("items", [])
        # 注目論文の日本語読み解き（tools/gen_paper_readings.py が生成）。
        # 無ければ個別ページを作らないだけで、ビルドは通る。
        # _load_json は未作成時に items=[] を返すので dict だけ受ける。
        readings = _load_json("paper_readings.json").get("items")
        self.paper_readings = readings if isinstance(readings, dict) else {}
        # 言語ごとに実際に出力したパスを記録（sitemap生成に使う）
        self.paths_by_lang: dict[str, list[str]] = {l: [] for l in config.LANGS}
        # canonical を他ページに向けたパス。sitemap には載せない
        # （正本でないURLを申告すると矛盾したシグナルになる）
        self.noncanonical: dict[str, set[str]] = {l: set() for l in config.LANGS}
        # noindex にしたページ。sitemap からも外す。
        # 入るのは2種類——自社の要約(body_long)がまだ無いニュース個別ページと、
        # 記事が1本も無いカテゴリページ。どちらも「中身が無いものは
        # 検索結果に出さない、中身が入れば自動で戻る」という同じ扱い。
        self.noindex_paths: dict[str, set[str]] = {l: set() for l in config.LANGS}
        # 記事ページ以外（トップ・一覧・ニュース）がSNSに貼られたときの画像。
        # 2026-08-01 まで static/img/ogp.png を指していたが、そのファイルは
        # 存在せず404だった（配信元にもリポジトリにも無い）。つまり X や
        # Slack に貼っても画像が出ていなかった。
        # サイトを象徴する識別画像を使う。記事ごとの写真は記事側で上書きする。
        _sym = config.STATIC_DIR / "img" / "oni-identity.jpg"
        self.og_fallback_image = (
            f"{self.base_url}/static/img/oni-identity.jpg" if _sym.exists() else "")

    # 相対パス prefix（dist直下=ルート、ページ深さに応じて ../ を積む）
    @staticmethod
    def _rel(depth: int) -> str:
        return "../" * depth if depth else ""

    def _lang_root(self, lang: str) -> str:
        """その言語のルート出力ディレクトリ（ja=dist, en=dist/en）。"""
        return config.DIST_DIR if lang == config.DEFAULT_LANG else config.DIST_DIR / lang

    def _url_for(self, lang: str, path: str) -> str:
        """絶対URL。path は 'news/' など（末尾スラッシュ）。"""
        prefix = "" if lang == config.DEFAULT_LANG else f"{lang}/"
        return f"{self.base_url}/{prefix}{path}"

    def _alternates(self, path: str) -> dict:
        return {l: self._url_for(l, path) for l in config.LANGS}

    def _ctx(self, lang: str, *, depth: int, active: str, path: str,
             page_description: str = "", title_suffix: str | None = None,
             noindex: bool = False, canonical_path: str | None = None) -> dict:
        rel = self._rel(depth)  # 言語ルート基準（ナビ用）
        # アセット(css/js/img)はサイトルート(dist/)基準。en配下は1階層深いので補正。
        asset = rel + ("../" if lang != config.DEFAULT_LANG else "")
        return {
            "lang": lang,
            "t": lambda k: _t(k, lang),
            "site_name": config.SITE_NAME,
            "site_tagline": config.SITE_TAGLINE[lang],
            "site_description": config.SITE_DESCRIPTION[lang],
            "page_description": page_description,
            # <title> の末尾に付く " · AIの鬼"。トップだけ空にして、
            # ブロック側でブランド名を先頭に置いた完全形を組む。
            "title_suffix": (f" · {config.SITE_NAME}"
                             if title_suffix is None else title_suffix),
            "home_title": config.HOME_TITLE,
            "hero_brand": config.HERO_BRAND,
            "hero_brand_sub": config.HERO_BRAND_SUB,
            # True なら noindex, follow を出す（ページネーション2以降・ソース別一覧）
            "noindex": noindex,
            # GA4。空なら base.html 側で計測タグを出力しない
            "ga4_id": config.GA4_MEASUREMENT_ID,
            "rel": rel,
            "asset": asset,
            "asset_ver": self.asset_ver,
            "home_url": rel or "./",
            "active": active,
            "year": self.year,
            "build_time": self.build_time,
            # canonical_path を渡すと、そのURLを正本として申告する。
            # 同一記事が複数の配信元から入って中身が同じページが2枚できたときに
            # 片方へ統合するために使う（2026-07-30、Qiita×Zennの相互投稿で4組）。
            "canonical": self._url_for(lang, canonical_path
                                       if canonical_path is not None else path),
            "site_base_url": self.base_url,
            # 記事カテゴリはナビ・カテゴリチップの両方で使うので常に渡す
            "article_categories": config.ARTICLE_CATEGORIES,
            "og_type": "article" if path.startswith("articles/") and path != "articles/" else "website",
            "alternates": self._alternates(path),
            # SNSに貼られたときの画像。記事ページは呼び出し側が share_image を
            # 上書きする。それ以外はここで決めた共通の1枚を使う。
            "og_fallback_image": self.og_fallback_image,
            "share_image": None,
            # フィルタに出すソース。英語サイトには英語ソースのみ
            # （日本語ソースの記事は英語サイトに載せないため）。
            "news_sources": [
                s for s in config.NEWS_SOURCES
                if lang != "en" or s["lang"] == "en"
            ],
            # AI可視性チェッカー（home.html のウィジェット）用。
            # 別ホスト(Vercel)の絶対URLと Turnstile サイトキーを渡す。
            "diagnose_endpoint": config.DIAGNOSE_ENDPOINT,
            "turnstile_site_key": config.TURNSTILE_SITE_KEY,
        }

    def _source_chips(self, lang: str, up: int, current: str | None) -> list[dict]:
        """ニュースのソース別絞り込みチップ。

        up はそのページから news/ まで戻る階層数。
        ページ分割後も絞り込みが機能するよう、実ページへのリンクとして出す。
        """
        back = "../" * up
        chips = [{"id": None, "name": _t("news.filter_all", lang),
                  "href": back or "./", "current": current is None}]
        for s in config.NEWS_SOURCES:
            if lang == "en" and s["lang"] != "en":
                continue
            chips.append({"id": s["id"], "name": s["name"],
                          "href": f"{back}source/{s['id']}/",
                          "current": current == s["id"]})
        return chips

    def _write(self, lang: str, path: str, html: str) -> None:
        out_dir = self._lang_root(lang) / path
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(html, encoding="utf-8")
        self.paths_by_lang[lang].append(path.rstrip("/") + "/")

    def _write_root(self, lang: str, html: str) -> None:
        out_dir = self._lang_root(lang)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "index.html").write_text(html, encoding="utf-8")
        self.paths_by_lang[lang].append("")

    def build_lang(self, lang: str) -> None:
        news = prepare_news(self.news_raw, lang)
        papers = prepare_papers(self.papers_raw, lang, self.paper_readings)
        articles = load_articles(lang)
        home_label = _t("nav.home", lang)

        # トップ（depth: ja=0, en=1 だが rel は言語ルート基準なので 0）
        # title_suffix="" … トップだけ config.HOME_TITLE をそのまま <title> にする
        # meta description は site_description（JSON-LD やOGPで使う正式な紹介文）
        # をそのまま流用していたが、197字あり検索結果では途中で切れて
        # 「…最新の研究・調査は中小」で終わっていた。検索結果に収まる長さで、
        # 何が読めるサイトかを先に言い切る文を別に持たせる。
        ctx = self._ctx(lang, depth=0, active="home", path="", title_suffix="",
                        page_description=config.HOME_META_DESCRIPTION.get(
                            lang, config.SITE_DESCRIPTION[lang]))
        # 注目5本は本数を固定する。読者に「これで主要な動きは押さえた」
        # という完了感を与えるため（可変だと読み終わりの判断ができない）。
        # ヒーローは画像がある記事だけを使う。
        # 画像なしだとグレーの矩形が出て、トップの見栄えが崩れるため。
        with_img = [n for n in news if n.get("image")]
        # メインの1本は「媒体の顔」になるので、新しい順に置くだけにしない。
        # 中小企業の経営者・情シス向けメディアとして相応しいものを選ぶ。
        featured = _order_featured(with_img)[:5]
        used = {id(n) for n in featured}
        latest = [n for n in news if id(n) not in used][:12]
        tcounts = topics.counts(news)
        topic_nav = [
            {"id": t["id"], "name": topics.name(t["id"], lang),
             "desc": topics.desc(t["id"], lang), "count": tcounts.get(t["id"], 0)}
            for t in topics.TOPICS if tcounts.get(t["id"], 0) >= 3
        ]
        topic_nav.sort(key=lambda x: -x["count"])
        # 自社記事（TOEの実践記録）をトップに出す。
        # 集約ニュースより先に置かないと、差別化要素が読者に伝わらない。
        # トップは「集約ニュース」ではなく「自社の実践記録」を主役に置く。
        # practice = 実践室＋失敗の鬼（何をやってどうなったかの記録）
        # observation = AEO対策室（AI検索対策の実務と実測。AEO導線でもある）
        practice = [a for a in articles
                    if a.get("category") in ("jissen", "shippai", "shigoto")]
        observation = [a for a in articles if a.get("category") == "aeo"]
        # AI解体新書（外部の研究・調査・事例を中小企業向けに読み解く解説）。
        # 一次記録ではないが本数の主力。実践・実測の下の第2階層として置く。
        explainer = [a for a in articles if a.get("category") == "kaisetsu"]
        # naka = 中の鬼（中の人の雑記）。実測ラボの手前で人間くささを見せる導線。
        naka = [a for a in articles if a.get("category") == "naka"]
        ctx.update(news=news, papers=papers, articles=articles,
                   featured=featured, latest=latest[:8], topic_nav=topic_nav,
                   hero_copy=config.HERO_COPY, hero_sub=config.HERO_SUB,
                   hero_sub_sp=config.HERO_SUB_SP,
                   practice=practice, observation=observation, explainer=explainer,
                   naka=naka,
                   proof_stats=config.PROOF_STATS,
                   news_count=len(news))
        ctx["jsonld"] = seo.build_jsonld(
            self.base_url, lang, "home",
            trail=[(home_label, self._url_for(lang, ""))])
        self._write_root(lang, self.env.get_template("home.html").render(**ctx))

        # 一覧ページ（言語ルートから1階層 → rel="../"）
        # 件数が多いものはページ分割する。1ページ目は news/、2ページ目以降は news/2/。
        # 一覧ページは自前の description を持たせる。
        # 2026-07-30 実測: /news/ /papers/ /articles/ とトップの4ページが
        # site_description をそのまま出力していて、検索結果で同一文が4回並んでいた。
        # 一覧に載せる件数。ニュースだけは保持件数（アーカイブ）と
        # 一覧の長さを分けている。config.NEWS_LIST_LIMIT のコメント参照。
        paged = [
            ("news/", "news.html", "news", "news",
             news[:config.NEWS_LIST_LIMIT],
             "国内外のAI開発元の発表と専門メディアを1日2回横断して集約。"
             "英語ソースは日本語に翻訳し、要点と中小企業の実務への影響を添えています。"),
            ("papers/", "papers.html", "papers", "papers", papers,
             "arXiv から機械学習・自然言語処理・コンピュータビジョンの最新プレプリントを"
             "集約。注目論文は日本語で読み解き、中小企業の実務に何を意味するかまで整理します。"),
            ("articles/", "articles.html", "articles", "articles", articles,
             "株式会社TOEが自社の業務でAIを動かした一次記録と、AI検索を実際に測った結果。"
             "処理件数・所要時間・失敗件数を実ログのまま載せています。"),
        ]
        total_pages_built = 0
        for base_path, tpl, active, var, all_items, list_desc in paged:
            chunks = _paginate(all_items, config.PAGE_SIZE)
            for pno, chunk in enumerate(chunks, 1):
                path = base_path if pno == 1 else f"{base_path}{pno}/"
                depth = 1 if pno == 1 else 2
                # 2ページ目以降は noindex, follow。
                # 実測（2026-07-30）で /papers/2〜8/ が表示の23%を吸って CTR 1.7%。
                # 一覧の断片が検索結果に出ても読者は答えに着地できない。
                # follow は残すので個別ページの発見性は落ちない。
                #
                # noindex でも title と description は個別化する。
                # noindex が効くまでのあいだ検索結果には出続けるうえ、
                # 2026-08-01 実測で /papers/ 〜 /papers/8/ の9ページが
                # すべて同じ「研究動向 (arXiv) · AIの鬼」＋同じ説明文で並び、
                # 151表示2クリック（CTR 1.3%）だった。何ページ目の何が
                # 載っているのか分からないものはクリックされない。
                page_desc = list_desc
                if pno > 1:
                    page_desc = f"{list_desc}（{pno}ページ目）"
                ctx = self._ctx(lang, depth=depth, active=active, path=path,
                                noindex=pno > 1, page_description=page_desc)
                ctx["page_title"] = (
                    None if pno == 1 else
                    f"{_t(f'{active}.title', lang)}（{pno}/{len(chunks)}ページ）")
                ctx[var] = chunk
                ctx["pagination"] = _pagination_ctx(pno, len(chunks))
                # 読み解きを用意した論文の入口は /papers/ の1ページ目だけに出す。
                # ここに出さないと、一覧1ページ目に載らなかった論文の個別ページが
                # noindex のページネーションからしかリンクされない。
                if active == "papers" and pno == 1 and self.paper_readings:
                    ctx["reading_index"] = sorted(
                        self.paper_readings.values(),
                        key=lambda r: r.get("published", ""), reverse=True)
                if active == "news":
                    ctx["source_chips"] = self._source_chips(
                        lang, up=depth - 1, current=None)
                ctx["jsonld"] = seo.build_jsonld(
                    self.base_url, lang, active,
                    trail=[(home_label, self._url_for(lang, "")),
                           (_t(f"nav.{active}", lang), self._url_for(lang, base_path))],
                    news=chunk if active == "news" else None,
                    papers=chunk if active == "papers" else None,
                    articles=chunk if active == "articles" else None)
                self._write(lang, path.rstrip("/"),
                            self.env.get_template(tpl).render(**ctx))
                total_pages_built += 1

        # カテゴリ別ページ（AI実践室・失敗の鬼・今週のAI・AEO対策室・AI仕事術）
        # このサイトの主役は集約ニュースではなく自社記事なので、
        # カテゴリごとに独立したURLを持たせて入口を増やす。
        #
        # <title> はコーナー名だけにしない（2026-08-13 実測）。
        # 「中の鬼」「失敗の鬼」はこのサイトの造語で、検索窓に打つ人がいない。
        # 20ある一覧・コーナーページで表示があったのは17、うちクリックが
        # 付いたのは指名検索から来る2ページだけだった。名前の後ろに
        # 「読者が実際に検索する言葉」を足す。h1（コーナー名）は変えない。
        for cat in config.ARTICLE_CATEGORIES:
            items = [a for a in articles if a.get("category") == cat["id"]]
            path = f"{cat['id']}/"
            # まだ1本も記事が無いカテゴリは検索結果に出さない。
            # 2026-08-01 実測で /weekly/ が「このカテゴリの記事はこれから
            # 公開します。」だけのページとして index 対象になっていた。
            # 中身の無いページを索引させると、サイト全体の評価を下げる。
            # 記事が入れば自動で index に戻る（薄いニュース個別ページと同じ扱い）。
            empty = not items
            if empty:
                self.noindex_paths[lang].add(path)   # sitemap からも外す
            ctx = self._ctx(lang, depth=1, active=cat["id"], path=path,
                            page_description=cat["desc"], noindex=empty)
            ctx["articles"] = items
            ctx["category"] = cat
            if lang == "ja" and cat["id"] in _CATEGORY_SEARCH_TITLE:
                ctx["page_title"] = _CATEGORY_SEARCH_TITLE[cat["id"]]
            ctx["pagination"] = None
            ctx["jsonld"] = seo.build_jsonld(
                self.base_url, lang, "articles",
                trail=[(home_label, self._url_for(lang, "")),
                       (cat["name"], self._url_for(lang, path))],
                articles=items)
            self._write(lang, path.rstrip("/"),
                        self.env.get_template("articles.html").render(**ctx))
            total_pages_built += 1

        # 記事詳細（articles/<slug>/ → depth 2）
        # 関連記事の照合キーを先に1回だけ作る（記事×記事の全組み合わせを回すため）
        for a in articles:
            a["_keys"] = _keyset(a.get("title", ""), a.get("excerpt", ""))
        rel_hits = 0
        for a in articles:
            path = f"articles/{a['slug']}/"
            page_url = self._url_for(lang, path)
            ctx = self._ctx(lang, depth=2, active="articles", path=path,
                            page_description=a.get("meta_desc")
                            or a.get("excerpt", ""))
            ctx["article"] = a
            # SNSに貼られたときは、その記事の写真を出す。
            if a.get("hero"):
                ctx["share_image"] = (
                    f"{self.base_url}/static/img/{a['hero']}"
                    if a.get("hero_is_local") else a["hero"])
            # 読み終えた人が次に読むもの。無関係なもので埋めない。
            ctx["related"] = related_articles(a, articles)
            if ctx["related"]:
                rel_hits += 1
            # 記事末の相談バナー。内容に応じて2商材から出し分ける。
            ctx["cta"] = business.cta_banner(
                cta_kind(a.get("title"), a.get("excerpt"),
                         category=a.get("category", "")), lang)
            ctx["cta_kind"] = cta_kind(a.get("title"), a.get("excerpt"),
                                       category=a.get("category", ""))
            ctx["jsonld"] = seo.build_jsonld(
                self.base_url, lang, "article", article=a, page_url=page_url,
                trail=[(home_label, self._url_for(lang, "")),
                       (_t("nav.articles", lang), self._url_for(lang, "articles/")),
                       (a["title"], page_url)])
            html = self.env.get_template("article.html").render(**ctx)
            self._write(lang, f"articles/{a['slug']}", html)
        print(f"  [{lang}] 関連記事が付いた記事 {rel_hits}/{len(articles)}件")

        # ニュース個別ページ（news/<slug>/ → depth 2）
        # 外部へ直接飛ばさず自サイトを経由させ、関連する自社記事へ回遊させる。
        # 元記事の全文は配信元リンクへ、画像は配信元URLの参照(ホットリンク)で
        # 表示し、当サーバーには保存しない（転載しない）。
        related_pool = [a for a in articles if a.get("category")
                        in ("jissen", "aeo", "kaisetsu", "shippai")]
        # 照合用キーを1回だけ作る（記事×ニュースの全組み合わせを回すため）
        for a in related_pool:
            a["_keys"] = _keyset(a.get("title", ""), a.get("excerpt", ""))
        matched_count = 0
        # 同じ記事を Qiita と Zenn の両方に投稿している著者がいるため、
        # 配信元が違うのに <title> が完全一致するページが生まれる
        # （2026-07-30 実測で4組）。重複するものだけ配信元名を足して区別する。
        # 中身が同じページが2枚できるので、最初に現れたものを正本にして
        # 残りは canonical でそこへ統合する。表示上は配信元名で区別する。
        # 突き合わせは2種類。
        #   ・display_title 一致 … 同じ記事を複数サイトに相互投稿した著者のケース
        #   ・要約本文一致     … 別媒体が同じニュースを報じ、要約が同一になったケース
        #                        （タイトルは違うので title だけでは検出できない）
        title_counts: dict[str, int] = {}
        canonical_of: dict[str, str] = {}
        body_counts: dict[str, int] = {}
        canonical_by_body: dict[str, str] = {}
        for n in news:
            key = n.get("display_title", "")
            title_counts[key] = title_counts.get(key, 0) + 1
            canonical_of.setdefault(key, f"news/{n['slug']}/")
            body = (n.get("body_long") or "").strip()
            if body:
                body_counts[body] = body_counts.get(body, 0) + 1
                canonical_by_body.setdefault(body, f"news/{n['slug']}/")

        dup_merged = 0
        for idx, n in enumerate(news):
            npath = f"news/{n['slug']}/"
            npage_url = self._url_for(lang, npath)
            title_tail, ndesc = news_meta(n, lang)
            key = n.get("display_title", "")
            body = (n.get("body_long") or "").strip()
            canon = None
            if title_counts.get(key, 0) > 1:
                title_tail = f"{title_tail}（{n.get('source', '')}）"
                if canonical_of[key] != npath:
                    canon = canonical_of[key]
            if canon is None and body and body_counts.get(body, 0) > 1:
                if canonical_by_body[body] != npath:
                    canon = canonical_by_body[body]
            if canon:
                dup_merged += 1
                self.noncanonical[lang].add(npath)
            # ニュース個別ページは「自社の本文が無いもの」だけ noindex にする。
            #
            # 経緯。2026-08-15 にこれを全件 noindex へ広げたところ、サイト全体の
            # 検索表示が 85/日 → 5/日 へ落ちた。実測で分かった仕組みはこう:
            #
            #   ・表示の73%は /news/ 個別ページで、その半分以上は「公開から3日以内」の
            #     新着ページが稼いでいた（実測: 新着率 36〜69%）。ニュースは鮮度で
            #     読まれるので、常に新しいページが index に入り続けることが生命線だった。
            #   ・全件 noindex にすると、以後に作られるニュースは**生まれた瞬間から
            #     検索に出られない**。既存ページの再クロールを待つまでもなく、
            #     新着の流入が即日で止まる。実測: 検索結果に新しく現れたURLは
            #     1日12〜20本 →（8/16以降）0〜3本。
            #   ・sitemap も 1,354 → 274 URL に縮んだため、サイト全体のクロール需要が
            #     落ちた。標本21本のうち 8/14 以降にクロールされたのは1本だけで、
            #     /articles/ も /papers/ も巻き添えで止まった。
            #
            # 一方で 8/15 の狙い（他社記事の要約が自社の顔になるのを止める）は正しい。
            # そこで線を「全件」ではなく「自社の本文があるか」に戻す。実測の裏付け:
            #
            #     自社本文あり   表示263 クリック15（CTR 5.7%）
            #     自社本文なし   表示488 クリック14（CTR 2.9%）
            #
            # 本文があるページは半分の表示で同じだけのクリックを取っている。
            # 検索に出すのはこちらだけにすれば、鮮度の流入は保ったまま、
            # 出典リンクしか無いページが当社の顔になることは防げる。
            #
            # 一覧（/news/ とカテゴリ）は index のまま。
            # noindex 側も follow なので、関連する自社記事への評価は通る。
            thin = not body
            if thin:
                self.noindex_paths[lang].add(npath)
            ctx = self._ctx(lang, depth=2, active="news", path=npath,
                            page_description=ndesc, canonical_path=canon,
                            noindex=thin)
            ctx["news"] = n
            ctx["news_title_tail"] = title_tail
            # <title> だけは丸める。h1 と OGP は display_title の全文のまま。
            ctx["news_head_title"] = head_title(n.get("display_title") or "")
            _nk = cta_kind(n.get("display_title"), n.get("display_summary"))
            ctx["cta"] = business.cta_banner(_nk, lang)
            ctx["cta_kind"] = _nk
            # まず本当に関連する記事。足りない分だけ従来のローテーションで補う。
            rel3 = relevance_ranked(n, related_pool) if related_pool else []
            if rel3:
                matched_count += 1
            if related_pool and len(rel3) < 3:
                chosen = {a["slug"] for a in rel3}
                start = (idx * 3) % len(related_pool)
                rotated = related_pool[start:] + related_pool[:start]
                for a in rotated:
                    if a["slug"] not in chosen:
                        rel3.append(a)
                        chosen.add(a["slug"])
                    if len(rel3) >= 3:
                        break
            ctx["related"] = rel3
            # 以前はニュース個別ページの JSON-LD が空文字だった（=構造化データ皆無）。
            # パン粉と、自社で書いた要約であることの明示を入れる。
            # 他社記事そのものを自作記事として申告はしない（seo.py の方針）。
            ctx["jsonld"] = seo.build_jsonld(
                self.base_url, lang, "news_detail", news_item=n,
                page_url=npage_url, page_description=ndesc,
                trail=[(home_label, self._url_for(lang, "")),
                       (_t("nav.news", lang), self._url_for(lang, "news/")),
                       (n.get("display_title", ""), npage_url)])
            html = self.env.get_template("news_article.html").render(**ctx)
            self._write(lang, f"news/{n['slug']}", html)
        if news:
            print(f"  [{lang}] 関連記事の実マッチ {matched_count}/{len(news)}件"
                  f" / 重複ニュースをcanonical統合 {dup_merged}件")

        # 注目論文の個別ページ（papers/<arxiv_id>/ → depth 2）
        # 全250件には作らない。読み解きを用意した本数だけ。
        # 全件に薄いページを作ると、集約ニュースで避けた「他社コンテンツを
        # 膨らませた大量ページ」を論文側で再生産することになる。
        paper_pages = 0
        for aid, pr in sorted(self.paper_readings.items()):
            ppath = f"papers/{aid}/"
            ppage_url = self._url_for(lang, ppath)
            pr = dict(pr)
            pr["published_display"] = fmt_date(pr.get("published"), lang)
            ctx = self._ctx(lang, depth=2, active="papers", path=ppath,
                            page_description=_clip(pr.get("one_line", ""), 110))
            ctx["paper"] = pr
            # ここも本当に関連する記事だけを出す（無ければ出さない）
            ctx["related"] = relevance_ranked(
                {"display_title": pr.get("title_ja", ""),
                 "title": pr.get("title_en", ""),
                 "body_long": " ".join(pr.get("points", []))
                              + pr.get("implication", "")},
                related_pool, limit=3) if related_pool else []
            ctx["jsonld"] = seo.build_jsonld(
                self.base_url, lang, "paper", paper=pr, page_url=ppage_url,
                trail=[(home_label, self._url_for(lang, "")),
                       (_t("nav.papers", lang), self._url_for(lang, "papers/")),
                       (pr.get("title_ja", ""), ppage_url)])
            self._write(lang, f"papers/{aid}",
                        self.env.get_template("paper.html").render(**ctx))
            paper_pages += 1
        if paper_pages:
            print(f"  [{lang}] 論文の個別ページ {paper_pages}本")
        total_pages_built += paper_pages

        # ソース別ニュースページ（news/source/<id>/）
        # ページ分割によりチップの絞り込みが現在ページ内に限定されてしまうため、
        # ソースごとに実ページを持たせる。検索インデックス上も有利。
        by_source: dict[str, list[dict]] = {}
        for n in news:
            by_source.setdefault(n.get("source_id", "other"), []).append(n)
        source_pages = 0
        for sid, items in by_source.items():
            src_name = next((s["name"] for s in config.NEWS_SOURCES if s["id"] == sid), sid)
            base_path = f"news/source/{sid}/"
            chunks = _paginate(items, config.PAGE_SIZE)
            for pno, chunk in enumerate(chunks, 1):
                path = base_path if pno == 1 else f"{base_path}{pno}/"
                depth = 3 if pno == 1 else 4
                # ソース別アーカイブは全ページ noindex, follow。
                # 実測（2026-07-30）で「the verge ai」という他社媒体名の検索で
                # /news/source/verge_ai/ が5.7位に出ていた。読者価値がなく、
                # 他社ブランド名で自社アーカイブが上位に出るのは避ける。
                # サイト内の絞り込み導線としては引き続き機能する。
                ctx = self._ctx(lang, depth=depth, active="news", path=path,
                                noindex=True,
                                page_description=f"{src_name} — {_t('news.subtitle', lang)}")
                ctx["news"] = chunk
                ctx["pagination"] = _pagination_ctx(pno, len(chunks))
                ctx["source_chips"] = self._source_chips(lang, up=depth - 1, current=sid)
                ctx["source_name"] = src_name
                ctx["jsonld"] = seo.build_jsonld(
                    self.base_url, lang, "news",
                    trail=[(home_label, self._url_for(lang, "")),
                           (_t("nav.news", lang), self._url_for(lang, "news/")),
                           (src_name, self._url_for(lang, base_path))],
                    news=chunk)
                self._write(lang, path.rstrip("/"),
                            self.env.get_template("news.html").render(**ctx))
                source_pages += 1
        total_pages_built += source_pages

        # FAQページ（FAQPage構造化データ付き＝AI検索に最も引用されやすい形式）
        faq_meta, faqs = load_faq(lang)
        if faqs:
            ctx = self._ctx(lang, depth=1, active="faq", path="faq/",
                            page_description=faq_meta.get("excerpt", ""))
            ctx["faqs"] = faqs
            ctx["faq_title"] = faq_meta.get("title", _t("faq.title", lang))
            ctx["faq_excerpt"] = faq_meta.get("excerpt", "")
            ctx["jsonld"] = seo.build_jsonld(
                self.base_url, lang, "faq", faqs=faqs,
                trail=[(home_label, self._url_for(lang, "")),
                       (_t("nav.faq", lang), self._url_for(lang, "faq/"))])
            self._write(lang, "faq", self.env.get_template("faq.html").render(**ctx))

        # サイト内検索ページ＋検索インデックス（サーバー不要）
        ctx = self._ctx(lang, depth=1, active="search", path="search/",
                        page_description=_t("search.subtitle", lang))
        ctx["jsonld"] = seo.build_jsonld(
            self.base_url, lang, "search",
            trail=[(home_label, self._url_for(lang, "")),
                   (_t("nav.search", lang), self._url_for(lang, "search/"))])
        self._write(lang, "search", self.env.get_template("search.html").render(**ctx))
        config.STATIC_DIR.mkdir(parents=True, exist_ok=True)
        (config.STATIC_DIR / f"search-{lang}.json").write_text(
            seo.build_search_index(lang, news, papers, articles),
            encoding="utf-8")

        # トピック別ページ（topics/<id>/）
        # 時系列一覧だけでは読者が関心領域にたどり着けないため、
        # 主題ごとの入口を実ページとして持たせる。
        topic_pages = 0
        for tp in topics.TOPICS:
            items = [n for n in news if tp["id"] in n.get("topics", [])]
            if len(items) < 3:
                continue
            base_path = f"topics/{tp['id']}/"
            chunks = _paginate(items, config.PAGE_SIZE)
            for pno, chunk in enumerate(chunks, 1):
                path = base_path if pno == 1 else f"{base_path}{pno}/"
                depth = 2 if pno == 1 else 3
                # 画面に出す一行は desc、検索結果に出す説明は meta。
                # 同じ文を兼ねさせると meta description が13〜21字にしかならない。
                ctx = self._ctx(lang, depth=depth, active="topics", path=path,
                                noindex=pno > 1,
                                page_description=topics.meta(tp["id"], lang))
                ctx["news"] = chunk
                ctx["pagination"] = _pagination_ctx(pno, len(chunks))
                ctx["topic_name"] = topics.name(tp["id"], lang)
                ctx["topic_desc"] = topics.desc(tp["id"], lang)
                ctx["topic_id"] = tp["id"]
                ctx["all_topics"] = [
                    {"id": x["id"], "name": topics.name(x["id"], lang),
                     "href": f"{'../' * (depth - 1)}{x['id']}/",
                     "current": x["id"] == tp["id"]}
                    for x in topics.TOPICS
                    if sum(1 for n in news if x["id"] in n.get("topics", [])) >= 3
                ]
                ctx["jsonld"] = seo.build_jsonld(
                    self.base_url, lang, "news",
                    trail=[(home_label, self._url_for(lang, "")),
                           (topics.name(tp["id"], lang), self._url_for(lang, base_path))],
                    news=chunk)
                self._write(lang, path.rstrip("/"),
                            self.env.get_template("topic.html").render(**ctx))
                topic_pages += 1
        total_pages_built += topic_pages

        # ニュース個別ページは生成しない（2026-07-19 方針変更）。
        #
        # 以前は a/<slug>/ に600件分のページを作り、要約を載せて自サイトを
        # 経由させていた。これをやめる。理由:
        #   1. 他社記事の要約を膨らませたページを大量に持つと、
        #      大量生成コンテンツと見なされ、サイト全体の評価が落ちる。
        #      オリジナル記事まで巻き添えになる。
        #   2. 要約を長くすると引用の範囲を超え、元記事の代替物になる。
        # 集約ニュースは一覧に留め、クリックは元記事へ直接送る。
        # このサイトの主役は集約ではなく自社の実践記録である。

        # AI検索対策の入口ページ(/check/)。記事末のAEOバナーはすべてここへ送る。
        # 日本語のみ。AEO対策の営業は国内向けで、英語ページを作っても
        # 中身が日本語のまま出るか、誰も踏まないページが増えるだけになる。
        if lang == config.DEFAULT_LANG:
            ctx = self._ctx(lang, depth=1, active="check", path="check/",
                            page_description=_t("check.subtitle", lang))
            # alternates は既定で全言語を出すが、このページは ja しか存在しない。
            # 存在しない en を hreflang で申告すると 404 を指すことになる。
            ctx["alternates"] = {lang: self._url_for(lang, "check/")}
            ctx["jsonld"] = seo.build_jsonld(
                self.base_url, lang, "check",
                trail=[(home_label, self._url_for(lang, "")),
                       (_t("check.title", lang), self._url_for(lang, "check/"))])
            self._write(lang, "check", self.env.get_template("check.html").render(**ctx))

        # 問い合わせ・広告ページ（収益導線。受け皿がなければ成果はゼロになる）
        ctx = self._ctx(lang, depth=1, active="contact", path="contact/",
                        page_description=_t("contact.subtitle", lang))
        ctx["contact_kinds"] = business.contact_kinds(lang)
        ctx["contact_email"] = config.CONTACT_EMAIL
        ctx["google_form_url"] = config.GOOGLE_FORM_URL
        ctx["google_form_height"] = config.GOOGLE_FORM_HEIGHT
        ctx["form_kinds"] = [k["label"] for k in business.contact_kinds(lang)]
        ctx["form_endpoint"] = config.FORM_ENDPOINT
        ctx["form_access_key"] = ""
        ctx["company_name"] = config.COMPANY_NAME
        ctx["company_url"] = config.COMPANY_URL
        ctx["jsonld"] = seo.build_jsonld(
            self.base_url, lang, "contact",
            trail=[(home_label, self._url_for(lang, "")),
                   (_t("contact.title", lang), self._url_for(lang, "contact/"))])
        self._write(lang, "contact", self.env.get_template("contact.html").render(**ctx))

        ctx = self._ctx(lang, depth=1, active="advertise", path="advertise/",
                        page_description=_t("ad.subtitle", lang))
        ctx["ad_audience"] = business.AD_AUDIENCE.get(lang, business.AD_AUDIENCE["ja"])
        ctx["ad_menu"] = business.AD_MENU.get(lang, business.AD_MENU["ja"])
        ctx["ad_mailto"] = business.ad_mailto()
        ctx["ad_stats"] = [
            {"n": len(news), "label": _t("nav.news", lang)},
            {"n": len(papers), "label": _t("nav.papers", lang)},
            {"n": len(articles), "label": _t("nav.articles", lang)},
        ]
        ctx["jsonld"] = seo.build_jsonld(
            self.base_url, lang, "advertise",
            trail=[(home_label, self._url_for(lang, "")),
                   (_t("ad.title", lang), self._url_for(lang, "advertise/"))])
        self._write(lang, "advertise", self.env.get_template("advertise.html").render(**ctx))

        # 運営会社。誰が運営しているかを明示するページ。
        ctx = self._ctx(lang, depth=1, active="about", path="about/",
                        page_description=_t("about.subtitle", lang))
        ctx["about_identity"] = business.ABOUT_IDENTITY.get(
            lang, business.ABOUT_IDENTITY["ja"])
        ctx["about_why"] = business.ABOUT_WHY.get(lang, business.ABOUT_WHY["ja"])
        ctx["about_policy"] = business.EDITORIAL_POLICY.get(
            lang, business.EDITORIAL_POLICY["ja"])
        ctx["company_profile"] = config.COMPANY_PROFILE
        ctx["jsonld"] = seo.build_jsonld(
            self.base_url, lang, "about",
            trail=[(home_label, self._url_for(lang, "")),
                   (_t("about.title", lang), self._url_for(lang, "about/"))])
        self._write(lang, "about", self.env.get_template("about.html").render(**ctx))
        total_pages_built += 3

        # RSSフィード
        feed = seo.build_feed(self.base_url, lang, articles, news, self.now)
        feed_dir = self._lang_root(lang)
        feed_dir.mkdir(parents=True, exist_ok=True)
        (feed_dir / "feed.xml").write_text(feed, encoding="utf-8")

        print(f"  [{lang}] home + {total_pages_built} 一覧ページ "
              f"+ {len(articles)} articles + feed.xml")

    # --- 付随ファイル ---
    def write_extras(self) -> None:
        # 静的アセット
        dest = config.DIST_DIR / "static"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(config.STATIC_DIR, dest)

        # .nojekyll（GitHub Pagesで _ 始まりを配信させる）
        (config.DIST_DIR / ".nojekyll").write_text("", encoding="utf-8")

        # CNAME（独自ドメイン）。サイトのルートに置く必要がある。
        if config.SITE_DOMAIN:
            (config.DIST_DIR / "CNAME").write_text(
                config.SITE_DOMAIN + "\n", encoding="utf-8")

        # robots.txt（検索エンジン＋AIクローラを明示許可）
        (config.DIST_DIR / "robots.txt").write_text(
            seo.build_robots(self.base_url), encoding="utf-8")

        # sitemap.xml（実際に生成したページのみ / lastmod + hreflang）
        # canonical を他へ向けたページと、noindex にしたページ（中身の無い
        # ニュース個別ページ・記事0本のカテゴリ）は除く
        articles_ja = load_articles(config.DEFAULT_LANG)
        sitemap_paths = {
            l: [p for p in paths
                if p not in self.noncanonical.get(l, set())
                and p not in self.noindex_paths.get(l, set())]
            for l, paths in self.paths_by_lang.items()
        }
        # 記事だけは実際の更新日を渡す。一覧やニュースは毎日中身が
        # 入れ替わるのでビルド日でよいが、記事は直した日を出さないと
        # 「毎日全記事を更新している」という嘘の申告になる。
        art_lastmod = {f"articles/{a['slug']}/": (a.get("updated") or a["date"])
                       for a in articles_ja if a.get("date")}
        (config.DIST_DIR / "sitemap.xml").write_text(
            seo.build_sitemap(self.base_url, sitemap_paths, self.now,
                              art_lastmod),
            encoding="utf-8")

        # IndexNow の鍵ファイル。検索エンジンがこれを取得して
        # サイト所有者であることを確認する（Webmaster Toolsのログイン不要）。
        (config.DIST_DIR / indexnow.key_filename()).write_text(
            indexnow.KEY, encoding="utf-8")

        # llms.txt（AI検索にサイト構造を伝える）
        articles_en = load_articles("en")
        (config.DIST_DIR / "llms.txt").write_text(
            seo.build_llms_txt(self.base_url, articles_ja, articles_en),
            encoding="utf-8")

        # llms-full.txt（自作コンテンツの全文をAIに提供。集約記事は著作権上含めない）
        for arts in (articles_ja, articles_en):
            for a in arts:
                a["plain"] = article_plain_text(a.get("html", ""))
        (config.DIST_DIR / "llms-full.txt").write_text(
            seo.build_llms_full(self.base_url, articles_ja, articles_en,
                                load_faq("ja")[1], load_faq("en")[1]),
            encoding="utf-8")

        # 404
        ctx = self._ctx(config.DEFAULT_LANG, depth=0, active="", path="404")
        four04 = self.env.from_string(_FOUR04_TPL).render(**ctx)
        (config.DIST_DIR / "404.html").write_text(four04, encoding="utf-8")
        # 旧URLの転送
        #
        # コーナー名を変えると一覧URLも変わる。GitHub Pages は 301 を返せない
        # ため、旧パスに meta refresh + canonical の1枚を置いて新URLへ送る。
        # 置かないと、外部リンク・ブックマーク・検索結果からの流入が
        # そのまま404に落ちる（旧 /kansoku/ は検索でクリックが付いていた）。
        # sitemap には入れない（self._write を通さないので自動的に外れる）。
        for old, new in config.REDIRECTS.items():
            target = f"{self.base_url}/{new}"
            out = config.DIST_DIR / old.strip("/") / "index.html"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                "<!doctype html><html lang=\"ja\"><head><meta charset=\"utf-8\">"
                f"<title>移転しました</title><link rel=\"canonical\" href=\"{target}\">"
                "<meta name=\"robots\" content=\"noindex, follow\">"
                f"<meta http-equiv=\"refresh\" content=\"0; url={target}\"></head>"
                f"<body><p>このページは <a href=\"{target}\">{target}</a> "
                "に移転しました。</p></body></html>",
                encoding="utf-8")

        extras = ("static/, .nojekyll, robots.txt, sitemap.xml, llms.txt, "
                  f"llms-full.txt, 404.html, indexnow-key, 転送{len(config.REDIRECTS)}件")
        if config.SITE_DOMAIN:
            extras += f", CNAME({config.SITE_DOMAIN})"
        print(f"  extras: {extras}")

    def run(self) -> None:
        print(f"=== AIの鬼 build @ {self.build_time} ===")
        print(f"  data: news={len(self.news_raw)} papers={len(self.papers_raw)}")
        # dist をクリーン
        if config.DIST_DIR.exists():
            shutil.rmtree(config.DIST_DIR)
        config.DIST_DIR.mkdir(parents=True)
        for lang in config.LANGS:
            self.build_lang(lang)
        self.write_extras()
        print(f"=== done → {config.DIST_DIR} ===")


# 404 は「行き止まり」にしない。
# 検索結果には、公開後しばらくしてから載る。その間にニュースが
# アーカイブ上限で押し出されていると、検索から来た読者がここに着く
# （2026-08-01 実測で96URLがこの状態だった）。上限は引き上げたが、
# 配信元が記事を消した場合など、着地し続けること自体は避けられない。
# Home ボタン1つで放り出さず、探しものに近い入口を並べる。
_FOUR04_TPL = """{% extends "base.html" %}
{% block title %}ページが見つかりません{% endblock %}
{% block content %}
<section class="section" style="padding:8vh 0">
  <div class="wrap" style="max-width:640px">
    <h1 style="font-size:clamp(2rem,7vw,3rem);margin:0 0 .5em">
      お探しのページは見つかりませんでした</h1>
    <p class="page-sub">
      URLが変わったか、掲載期間を終えた可能性があります。
      下から近いものを探せます。</p>
    {# 404.html は /news/<消えたslug>/ など任意の深さのURLで表示される。
       相対パスだと存在しない階層を指すのでサイト絶対パスで書く。 #}
    <ul style="line-height:2.2;margin:1.5em 0">
      <li><a href="/news/">AIニュース一覧</a>
        — 国内外の発表と専門メディアを毎日集約</li>
      <li><a href="/articles/">記事一覧</a>
        — TOEが自社でAIを動かした実測記録</li>
      <li><a href="/papers/">研究動向</a>
        — arXiv の最新プレプリントと日本語の読み解き</li>
      <li><a href="/search/">サイト内検索</a>
        — キーワードで探す</li>
    </ul>
    <a class="btn btn-primary" href="/">トップへ戻る</a>
  </div>
</section>
{% endblock %}"""


def main() -> int:
    Builder().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

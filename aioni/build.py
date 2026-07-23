"""静的サイトジェネレータ。

data/*.json（収集結果）+ content/articles/*.md（手書き記事）を読み、
日本語の静的サイトを dist/ に生成する。外部通信・AI APIは一切なし。

出力構成:
    dist/index.html            日本語トップ
    dist/news/ papers/ articles/ jissen/ shippai/ weekly/ kansoku/ shigoto/
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
from datetime import datetime, timezone

import markdown
from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import business, config, indexnow, seo, topics
from .i18n import t as _t


# --- データ読み込み -----------------------------------------------------
def _load_json(name: str) -> dict:
    path = config.DATA_DIR / name
    if not path.exists():
        return {"items": [], "generated_at": None}
    return json.loads(path.read_text(encoding="utf-8"))


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
_ARTICLE_CAT_TO_TOPIC = {
    "jissen": "tools",
    "shippai": "policy",
    "weekly": "models",
    "kansoku": "research",
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


def prepare_papers(raw: list[dict], lang: str) -> list[dict]:
    out = []
    for it in raw:
        it = dict(it)
        it["published_display"] = fmt_date(it.get("published"), lang)
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


def load_articles(lang: str) -> list[dict]:
    """content/articles/<slug>.<lang>.md を読み込む。"""
    if not config.ARTICLES_DIR.exists():
        return []
    md = markdown.Markdown(extensions=["extra", "toc", "sane_lists"])
    articles = []
    for path in sorted(config.ARTICLES_DIR.glob(f"*.{lang}.md")):
        slug = path.name[: -len(f".{lang}.md")]
        meta, body = _parse_frontmatter(path.read_text(encoding="utf-8"))
        md.reset()
        html = md.convert(body)
        tag = meta.get("tag", "")
        cat = config.CATEGORY_BY_TAG.get(tag)
        # hero 指定が無い記事には、カテゴリに応じたイメージ写真を当てる。
        # 一覧でグレーの矩形が並ぶと、記事そのものが読まれなくなるため。
        hero = meta.get("hero", "")
        if not hero:
            hero = _fallback_image(
                [_ARTICLE_CAT_TO_TOPIC.get(cat["id"] if cat else "", "")], slug)
        # 本文から読了時間を出す。読む前に「これは長いのか」が分かる方が親切。
        text_len = len(re.sub(r"<[^>]+>", "", html))
        articles.append({
            "slug": slug,
            "title": meta.get("title", slug),
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
    if item.get("body_ja"):        # 本文要約があるページは読み応えがある
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
        self.news_raw = _load_json("news.json").get("items", [])
        self.papers_raw = _load_json("papers.json").get("items", [])
        # 言語ごとに実際に出力したパスを記録（sitemap生成に使う）
        self.paths_by_lang: dict[str, list[str]] = {l: [] for l in config.LANGS}

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
             page_description: str = "") -> dict:
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
            # GA4。空なら base.html 側で計測タグを出力しない
            "ga4_id": config.GA4_MEASUREMENT_ID,
            "rel": rel,
            "asset": asset,
            "asset_ver": self.asset_ver,
            "home_url": rel or "./",
            "active": active,
            "year": self.year,
            "build_time": self.build_time,
            "canonical": self._url_for(lang, path),
            "site_base_url": self.base_url,
            # 記事カテゴリはナビ・カテゴリチップの両方で使うので常に渡す
            "article_categories": config.ARTICLE_CATEGORIES,
            "og_type": "article" if path.startswith("articles/") and path != "articles/" else "website",
            "alternates": self._alternates(path),
            # フィルタに出すソース。英語サイトには英語ソースのみ
            # （日本語ソースの記事は英語サイトに載せないため）。
            "news_sources": [
                s for s in config.NEWS_SOURCES
                if lang != "en" or s["lang"] == "en"
            ],
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
        papers = prepare_papers(self.papers_raw, lang)
        articles = load_articles(lang)
        home_label = _t("nav.home", lang)

        # トップ（depth: ja=0, en=1 だが rel は言語ルート基準なので 0）
        ctx = self._ctx(lang, depth=0, active="home", path="")
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
        # observation = AI検索観測所（独自調査。AEO導線でもある）
        practice = [a for a in articles
                    if a.get("category") in ("jissen", "shippai", "shigoto")]
        observation = [a for a in articles if a.get("category") == "kansoku"]
        # AI解体新書（外部の研究・調査・事例を中小企業向けに読み解く解説）。
        # 一次記録ではないが本数の主力。実践・実測の下の第2階層として置く。
        explainer = [a for a in articles if a.get("category") == "kaisetsu"]
        ctx.update(news=news, papers=papers, articles=articles,
                   featured=featured, latest=latest[:6], topic_nav=topic_nav,
                   hero_copy=config.HERO_COPY, hero_sub=config.HERO_SUB,
                   practice=practice, observation=observation, explainer=explainer,
                   proof_stats=config.PROOF_STATS,
                   news_count=len(news))
        ctx["jsonld"] = seo.build_jsonld(
            self.base_url, lang, "home",
            trail=[(home_label, self._url_for(lang, ""))])
        self._write_root(lang, self.env.get_template("home.html").render(**ctx))

        # 一覧ページ（言語ルートから1階層 → rel="../"）
        # 件数が多いものはページ分割する。1ページ目は news/、2ページ目以降は news/2/。
        paged = [
            ("news/", "news.html", "news", "news", news),
            ("papers/", "papers.html", "papers", "papers", papers),
            ("articles/", "articles.html", "articles", "articles", articles),
        ]
        total_pages_built = 0
        for base_path, tpl, active, var, all_items in paged:
            chunks = _paginate(all_items, config.PAGE_SIZE)
            for pno, chunk in enumerate(chunks, 1):
                path = base_path if pno == 1 else f"{base_path}{pno}/"
                depth = 1 if pno == 1 else 2
                ctx = self._ctx(lang, depth=depth, active=active, path=path)
                ctx[var] = chunk
                ctx["pagination"] = _pagination_ctx(pno, len(chunks))
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

        # カテゴリ別ページ（AI実践室・失敗の鬼・今週のAI・AI検索観測所・AI仕事術）
        # このサイトの主役は集約ニュースではなく自社記事なので、
        # カテゴリごとに独立したURLを持たせて入口を増やす。
        for cat in config.ARTICLE_CATEGORIES:
            items = [a for a in articles if a.get("category") == cat["id"]]
            path = f"{cat['id']}/"
            ctx = self._ctx(lang, depth=1, active=cat["id"], path=path,
                            page_description=cat["desc"])
            ctx["articles"] = items
            ctx["category"] = cat
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
        for a in articles:
            path = f"articles/{a['slug']}/"
            page_url = self._url_for(lang, path)
            ctx = self._ctx(lang, depth=2, active="articles", path=path,
                            page_description=a.get("excerpt", ""))
            ctx["article"] = a
            ctx["jsonld"] = seo.build_jsonld(
                self.base_url, lang, "article", article=a, page_url=page_url,
                trail=[(home_label, self._url_for(lang, "")),
                       (_t("nav.articles", lang), self._url_for(lang, "articles/")),
                       (a["title"], page_url)])
            html = self.env.get_template("article.html").render(**ctx)
            self._write(lang, f"articles/{a['slug']}", html)

        # ニュース個別ページ（news/<slug>/ → depth 2）
        # 外部へ直接飛ばさず自サイトを経由させ、関連する自社記事へ回遊させる。
        # 元記事の全文は配信元リンクへ、画像は配信元URLの参照(ホットリンク)で
        # 表示し、当サーバーには保存しない（転載しない）。
        related_pool = [a for a in articles if a.get("category")
                        in ("jissen", "kansoku", "kaisetsu", "shippai")]
        for idx, n in enumerate(news):
            npath = f"news/{n['slug']}/"
            ctx = self._ctx(lang, depth=2, active="news", path=npath,
                            page_description=n.get("display_title", ""))
            ctx["news"] = n
            if related_pool:
                start = (idx * 3) % len(related_pool)
                rel3 = related_pool[start:start + 3]
                if len(rel3) < 3:
                    rel3 = rel3 + related_pool[:3 - len(rel3)]
            else:
                rel3 = []
            ctx["related"] = rel3
            ctx["jsonld"] = ""
            html = self.env.get_template("news_article.html").render(**ctx)
            self._write(lang, f"news/{n['slug']}", html)

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
                ctx = self._ctx(lang, depth=depth, active="news", path=path,
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
                ctx = self._ctx(lang, depth=depth, active="topics", path=path,
                                page_description=topics.desc(tp["id"], lang))
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
        articles_ja = load_articles(config.DEFAULT_LANG)
        (config.DIST_DIR / "sitemap.xml").write_text(
            seo.build_sitemap(self.base_url, self.paths_by_lang, self.now),
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
        extras = ("static/, .nojekyll, robots.txt, sitemap.xml, llms.txt, "
                  "llms-full.txt, 404.html, indexnow-key")
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


_FOUR04_TPL = """{% extends "base.html" %}
{% block title %}404{% endblock %}
{% block content %}
<section class="section" style="text-align:center;padding:12vh 0">
  <div class="wrap">
    <h1 style="font-size:clamp(3rem,12vw,7rem);margin:0">404</h1>
    <p class="page-sub">お探しのページは見つかりませんでした。</p>
    <a class="btn btn-primary" href="{{ home_url or './' }}">Home</a>
  </div>
</section>
{% endblock %}"""


def main() -> int:
    Builder().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

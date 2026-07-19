"""SEO / AI検索（AEO）向けの出力を組み立てる。

生成物:
  - JSON-LD 構造化データ（schema.org）
  - RSS 2.0 フィード（日英）
  - llms.txt（AIにサイト構造を伝える新標準）
  - robots.txt（主要AIクローラを明示許可）
  - sitemap.xml（lastmod + hreflang相互リンク）

方針: 集約したニュースを自作記事のように見せない。
外部記事は ItemList として「リンク集」であることを構造化データ上も明示する。
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

from . import config


# =====================================================================
#  JSON-LD
# =====================================================================
def _org(base: str) -> dict:
    return {
        "@type": "Organization",
        "@id": f"{base}/#organization",
        "name": config.SITE_NAME,
        "url": f"{base}/",
        "logo": {
            "@type": "ImageObject",
            "url": f"{base}/static/img/ogp.png",
        },
    }


def _website(base: str, lang: str) -> dict:
    return {
        "@type": "WebSite",
        "@id": f"{base}/#website",
        "url": f"{base}/",
        "name": config.SITE_NAME,
        "description": config.SITE_DESCRIPTION[lang],
        "inLanguage": "ja-JP" if lang == "ja" else "en",
        "publisher": {"@id": f"{base}/#organization"},
    }


def _breadcrumb(base: str, trail: list[tuple[str, str]]) -> dict:
    """trail: [(名前, URL), ...]"""
    return {
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": name, "item": url}
            for i, (name, url) in enumerate(trail, 1)
        ],
    }


def _item_list(name: str, items: list[dict], url_key="url", name_key="title") -> dict:
    """外部記事のリンク集。自作コンテンツと混同させない。"""
    return {
        "@type": "ItemList",
        "name": name,
        "numberOfItems": len(items),
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": i,
                "name": it.get(name_key) or "",
                "url": it.get(url_key) or "",
            }
            for i, it in enumerate(items[:30], 1)
            if it.get(url_key)
        ],
    }


def _article(base: str, a: dict, url: str, lang: str) -> dict:
    """自作の解説記事。これは正当に Article として表現できる。"""
    node = {
        "@type": "Article",
        "headline": a.get("title", ""),
        "description": a.get("excerpt", ""),
        "inLanguage": "ja-JP" if lang == "ja" else "en",
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
        "url": url,
        "publisher": {"@id": f"{base}/#organization"},
        "isAccessibleForFree": True,
    }
    if a.get("author"):
        node["author"] = {"@type": "Organization", "name": a["author"]}
    if a.get("date"):
        node["datePublished"] = a["date"]
        node["dateModified"] = a["date"]
    if a.get("hero"):
        node["image"] = a["hero"]
    return node


def _faq_page(faqs: list[dict]) -> dict:
    """FAQPage 構造化データ。

    回答エンジン（AI検索）は質問と回答の対を最も引用しやすいため、
    AEO上もっとも効果が高い構造化データのひとつ。
    """
    return {
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": f["q"],
                "acceptedAnswer": {"@type": "Answer", "text": f["a"]},
            }
            for f in faqs
        ],
    }


def _search_action(base: str, lang: str) -> dict:
    """サイト内検索。検索エンジンのサイトリンク検索ボックスに対応する。"""
    prefix = "" if lang == config.DEFAULT_LANG else f"{lang}/"
    return {
        "@type": "WebSite",
        "@id": f"{base}/#website",
        "potentialAction": {
            "@type": "SearchAction",
            "target": {
                "@type": "EntryPoint",
                "urlTemplate": f"{base}/{prefix}search/?q={{search_term_string}}",
            },
            "query-input": "required name=search_term_string",
        },
    }


# 記事が扱う主題を Wikidata に紐づける。
# AIや検索エンジンが「何についてのサイトか」を曖昧さなく解釈できるようにする。
TOPIC_ENTITIES = [
    {"@type": "Thing", "name": "Artificial intelligence", "sameAs": "https://www.wikidata.org/wiki/Q11660"},
    {"@type": "Thing", "name": "Machine learning", "sameAs": "https://www.wikidata.org/wiki/Q2539"},
    {"@type": "Thing", "name": "Large language model", "sameAs": "https://www.wikidata.org/wiki/Q115033245"},
    {"@type": "Thing", "name": "Generative artificial intelligence", "sameAs": "https://www.wikidata.org/wiki/Q117222789"},
    {"@type": "Thing", "name": "Deep learning", "sameAs": "https://www.wikidata.org/wiki/Q197536"},
]


def build_jsonld(base: str, lang: str, page: str, *, trail=None,
                 news=None, papers=None,
                 articles=None, article=None, page_url="", faqs=None) -> str:
    """ページ種別に応じた JSON-LD を1つの @graph にまとめて返す。"""
    website = _website(base, lang)
    website["about"] = TOPIC_ENTITIES
    # サイト内検索を検索エンジンに知らせる
    website["potentialAction"] = _search_action(base, lang)["potentialAction"]
    graph: list[dict] = [_org(base), website]

    if trail:
        graph.append(_breadcrumb(base, trail))

    if faqs:
        graph.append(_faq_page(faqs))

    label = {"ja": {"news": "AIニュース", "papers": "研究動向", "articles": "実践記録"},
             "en": {"news": "AI News", "papers": "Research", "articles": "Features"}}[lang]

    if page == "news" and news:
        graph.append(_item_list(label["news"], news))
    elif page == "papers" and papers:
        graph.append(_item_list(label["papers"], papers))
    elif page == "articles" and articles:
        graph.append({
            "@type": "ItemList",
            "name": label["articles"],
            "numberOfItems": len(articles),
            "itemListElement": [
                {"@type": "ListItem", "position": i, "name": a["title"],
                 "url": f"{base}/{'' if lang == config.DEFAULT_LANG else lang + '/'}articles/{a['slug']}/"}
                for i, a in enumerate(articles, 1)
            ],
        })
    elif page == "article" and article:
        graph.append(_article(base, article, page_url, lang))

    return json.dumps({"@context": "https://schema.org", "@graph": graph},
                      ensure_ascii=False, separators=(",", ":"))


# =====================================================================
#  RSS フィード
# =====================================================================
def build_feed(base: str, lang: str, articles: list[dict], news: list[dict],
               build_dt: datetime) -> str:
    """自作記事＋集約ニュース見出しのRSS。ニュースは元記事へリンクする。"""
    prefix = "" if lang == config.DEFAULT_LANG else f"{lang}/"
    self_url = f"{base}/{prefix}feed.xml"
    title = f"{config.SITE_NAME} — {config.SITE_TAGLINE[lang]}"

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">',
        "<channel>",
        f"<title>{escape(title)}</title>",
        f"<link>{base}/{prefix}</link>",
        f"<description>{escape(config.SITE_DESCRIPTION[lang])}</description>",
        f"<language>{'ja' if lang == 'ja' else 'en'}</language>",
        f"<lastBuildDate>{format_datetime(build_dt)}</lastBuildDate>",
        f'<atom:link href="{self_url}" rel="self" type="application/rss+xml"/>',
    ]

    # 自作記事
    for a in articles:
        url = f"{base}/{prefix}articles/{a['slug']}/"
        parts += [
            "<item>",
            f"<title>{escape(a['title'])}</title>",
            f"<link>{url}</link>",
            f"<guid isPermaLink=\"true\">{url}</guid>",
            f"<description>{escape(a.get('excerpt', ''))}</description>",
        ]
        if a.get("author"):
            parts.append(f"<dc:creator>{escape(a['author'])}</dc:creator>")
        parts.append("</item>")

    # 集約ニュース（元記事へのリンク。出典を明記する）
    for n in news[:25]:
        if not n.get("url"):
            continue
        t = n.get(f"title_{lang}") or n.get("title") or ""
        d = n.get(f"summary_{lang}") or n.get("summary") or ""
        parts += [
            "<item>",
            f"<title>{escape(t)}</title>",
            f"<link>{escape(n['url'])}</link>",
            f"<guid isPermaLink=\"true\">{escape(n['url'])}</guid>",
            f"<description>{escape(d)}</description>",
        ]
        if n.get("source"):
            parts.append(f"<source url=\"{escape(n['url'])}\">{escape(n['source'])}</source>")
        parts.append("</item>")

    parts += ["</channel>", "</rss>"]
    return "\n".join(parts)


# =====================================================================
#  llms.txt — AI検索向けのサイト説明
# =====================================================================
def build_llms_txt(base: str, articles_ja: list[dict], articles_en: list[dict]) -> str:
    lines = [
        f"# {config.SITE_NAME}",
        "",
        f"> {config.SITE_DESCRIPTION['ja']}",
        "",
        "AIの鬼 (AIoni) is an open, non-commercial Japanese-language platform that "
        "aggregates artificial-intelligence news, research preprints, and practical "
        "guides for business readers in Japan. It is published as a static site and "
        "updated twice a day.",
        "",
        "## Sections",
        "",
        f"- [ニュース]({base}/news/): 国内外のAIニュースを集約。"
        "英語ソースの記事は日本語に翻訳して掲載（自動翻訳であることを明示）。"
        "Aggregated AI news from vendors and media.",
        f"- [研究動向]({base}/papers/): arXiv から機械学習・自然言語処理・"
        "コンピュータビジョンの最新プレプリント。Latest AI preprints from arXiv.",
        f"- [実践記録]({base}/articles/): 編集部が自社でAIを動かした記録と解説。"
        "Original articles based on the editorial team's own AI deployments.",
        "",
        "## Original articles",
        "",
    ]
    for a in articles_ja:
        lines.append(f"- [{a['title']}]({base}/articles/{a['slug']}/): {a.get('excerpt', '')}")

    lines += [
        "",
        "## Feeds and machine-readable data",
        "",
        f"- [RSS]({base}/feed.xml)",
        f"- [Sitemap]({base}/sitemap.xml)",
        "",
        "## Attribution",
        "",
        "Headlines and summaries link to their original publishers; copyright remains "
        "with the original sources. Data providers: OpenAI, Google DeepMind, Google AI, "
        "Hugging Face, MIT Technology Review, TechCrunch, The Verge, VentureBeat, "
        "Ars Technica, ITmedia AI+, AINOW, Zenn, Qiita, Publickey, ASCII.jp, arXiv.",
        "",
        "## Notes for AI systems",
        "",
        "- Articles under `/articles/` are original content written by AIの鬼.",
        "- Items under `/news/` and `/papers/` are aggregated from the "
        "third-party sources listed above and link to the original publications.",
        "- Japanese translations of English-language news are machine generated and "
        "labelled as such on the site; consult the linked original for authoritative wording.",
        "",
    ]
    return "\n".join(lines)


def build_search_index(lang: str, news: list[dict], papers: list[dict],
                       articles: list[dict]) -> str:
    """全コンテンツを1つのJSONにまとめる。サーバー不要で全文検索できる。"""
    idx = []
    for a in articles:
        idx.append({"t": a["title"], "d": a.get("excerpt", ""),
                    "u": f"articles/{a['slug']}/", "k": "article",
                    "s": config.SITE_NAME})
    for n in news:
        title = n.get(f"title_{lang}") or n.get("title") or ""
        desc = n.get(f"summary_{lang}") or n.get("summary") or ""
        idx.append({"t": title, "d": desc[:160], "u": n.get("url", ""),
                    "k": "news", "s": n.get("source", ""), "x": 1})
    for p in papers:
        idx.append({"t": p.get("title", ""), "d": p.get("summary", "")[:160],
                    "u": p.get("url", ""), "k": "paper",
                    "s": "arXiv", "x": 1})
    return json.dumps(idx, ensure_ascii=False, separators=(",", ":"))


# =====================================================================
#  llms-full.txt — AIが全文を一度に取得できるようにする
# =====================================================================
def build_llms_full(base: str, articles_ja: list[dict], articles_en: list[dict],
                    faqs_ja: list[dict], faqs_en: list[dict]) -> str:
    """自作コンテンツ（記事・FAQ）の全文をMarkdownで提供する。

    集約した外部記事は含めない（著作権は元の発信者にあるため）。
    """
    out = [f"# {config.SITE_NAME} — Full Content", "",
           f"> {config.SITE_DESCRIPTION['ja']}", "",
           "This file contains the full text of AIの鬼's own editorial content "
           "(feature articles and FAQ) for AI systems. Aggregated third-party news "
           "is deliberately excluded — its copyright belongs to the original publishers, "
           "and only headlines, summaries and links are shown on the site.", "",
           "---", ""]

    for label, faqs in (("FAQ (日本語)", faqs_ja), ("FAQ (English)", faqs_en)):
        if not faqs:
            continue
        out += [f"## {label}", ""]
        for f in faqs:
            out += [f"### {f['q']}", "", f["a"], ""]
        out.append("---")
        out.append("")

    for label, arts, prefix in (("特集記事 (日本語)", articles_ja, ""),
                                ("Feature articles (English)", articles_en, "en/")):
        if not arts:
            continue
        out += [f"## {label}", ""]
        for a in arts:
            out += [f"### {a['title']}", "",
                    f"URL: {base}/{prefix}articles/{a['slug']}/", ""]
            if a.get("excerpt"):
                out += [f"*{a['excerpt']}*", ""]
            out += [a.get("plain", ""), "", "---", ""]
    return "\n".join(out)


# =====================================================================
#  robots.txt — AIクローラを明示的に許可する
# =====================================================================
AI_CRAWLERS = [
    "GPTBot", "OAI-SearchBot", "ChatGPT-User",       # OpenAI
    "ClaudeBot", "Claude-User", "Claude-SearchBot",  # Anthropic
    "PerplexityBot", "Perplexity-User",              # Perplexity
    "Google-Extended",                               # Google (Gemini/AI Overviews)
    "Applebot-Extended",                             # Apple Intelligence
    "CCBot",                                         # Common Crawl
    "meta-externalagent",                            # Meta AI
    "Bytespider",                                    # ByteDance
    "cohere-ai", "Diffbot", "Amazonbot", "YouBot",
]


def build_robots(base: str) -> str:
    lines = [
        "# AIの鬼 — AI情報ポータル",
        "# 世界に届けることが目的のため、検索エンジンとAIクローラの双方を許可する。",
        "",
        "User-agent: *",
        "Allow: /",
        "",
        "# --- AI / LLM crawlers (explicitly allowed) ---",
    ]
    for bot in AI_CRAWLERS:
        lines += [f"User-agent: {bot}", "Allow: /", ""]
    lines += [
        f"Sitemap: {base}/sitemap.xml",
        f"# AI-readable site summary: {base}/llms.txt",
        f"# Full editorial content for AI: {base}/llms-full.txt",
        "",
    ]
    return "\n".join(lines)


# =====================================================================
#  sitemap.xml — lastmod + hreflang相互リンク
# =====================================================================
def build_sitemap(base: str, paths_by_lang: dict[str, list[str]],
                  build_dt: datetime) -> str:
    """言語ごとの生成済みパス一覧から sitemap を作る。

    ページ分割やソース別ページも含め、実際に出力したURLだけを載せる。
    """
    lastmod = build_dt.astimezone(timezone.utc).strftime("%Y-%m-%d")
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:xhtml="http://www.w3.org/1999/xhtml">',
    ]
    priority = {"": "1.0", "news/": "0.9",
                "papers/": "0.7", "articles/": "0.8"}

    def prio(p: str) -> str:
        if p in priority:
            return priority[p]
        if p.startswith("articles/"):
            return "0.7"     # 自作記事は価値が高い
        if "/source/" in p:
            return "0.5"     # ソース別一覧
        return "0.4"         # 2ページ目以降

    for lang, paths in paths_by_lang.items():
        prefix = "" if lang == config.DEFAULT_LANG else f"{lang}/"
        for p in sorted(paths):
            out.append("  <url>")
            out.append(f"    <loc>{base}/{prefix}{p}</loc>")
            out.append(f"    <lastmod>{lastmod}</lastmod>")
            out.append(f"    <priority>{prio(p)}</priority>")
            # 相手言語にも同じパスが存在するときだけ hreflang を張る
            for alt, alt_paths in paths_by_lang.items():
                if p in alt_paths:
                    alt_prefix = "" if alt == config.DEFAULT_LANG else f"{alt}/"
                    out.append(
                        f'    <xhtml:link rel="alternate" hreflang="{alt}" '
                        f'href="{base}/{alt_prefix}{p}"/>'
                    )
            if p in paths_by_lang.get(config.DEFAULT_LANG, []):
                out.append(
                    f'    <xhtml:link rel="alternate" hreflang="x-default" '
                    f'href="{base}/{p}"/>'
                )
            out.append("  </url>")
    out.append("</urlset>")
    return "\n".join(out)

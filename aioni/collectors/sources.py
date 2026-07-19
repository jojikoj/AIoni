"""各データソースからの取得ロジック。

すべて無料の公開API/RSS。個別ソースの失敗は例外を握りつぶさず
呼び出し側へ返し、orchestrator がフェイルソフト処理する。
戻り値は正規化済みの dict。
"""
from __future__ import annotations

import html
import re
import sys
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import feedparser
import requests

from .. import config


def _get(url: str) -> requests.Response:
    r = requests.get(
        url, timeout=config.HTTP_TIMEOUT,
        headers={"User-Agent": config.USER_AGENT, "Accept": "application/json, text/xml, */*"},
    )
    r.raise_for_status()
    return r


_TAG_RE = re.compile(r"<[^>]+>")


def clean_text(raw: str, limit: int = 320) -> str:
    """HTMLタグ・エンティティを除去して要約用の平文にする。"""
    if not raw:
        return ""
    text = _TAG_RE.sub(" ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


# --- 話題フィルタ -------------------------------------------------------
# AI以外も配信する総合メディア向け。AI関連語を含む記事だけを採用する。
_AI_TERMS = [
    # 英語（一般語）
    "ai", "artificial intelligence", "machine learning", "deep learning",
    "neural network", "llm", "large language model", "generative", "genai",
    "transformer", "diffusion", "embedding", "fine-tuning", "rag",
    "prompt", "inference", "agentic", "multimodal", "reinforcement learning",
    # 英語（固有名詞）
    "openai", "chatgpt", "gpt-", "anthropic", "claude", "gemini", "deepmind",
    "llama", "mistral", "hugging face", "stable diffusion", "midjourney",
    "copilot", "nvidia", "cuda", "sora", "perplexity", "grok", "deepseek",
    # 日本語
    "生成ai", "人工知能", "機械学習", "深層学習", "ディープラーニング",
    "ニューラルネット", "大規模言語モデル", "言語モデル", "推論", "学習モデル",
    "チャットgpt", "画像生成", "音声認識", "自然言語処理", "エージェント",
    "プロンプト", "ファインチューニング", "アノテーション", "半導体",
]


def is_ai_related(item: dict) -> bool:
    """記事がAI関連かどうかを判定する（総合メディア向けの絞り込み）。

    "ai" は2文字で誤検知しやすいため、単語境界で照合する。
    """
    import re as _re
    blob = f"{item.get('title', '')} {item.get('summary', '')}".lower()
    for term in _AI_TERMS:
        if term.isascii():
            if _re.search(rf"(?<![a-z0-9]){_re.escape(term)}(?![a-z])", blob):
                return True
        elif term in blob:
            return True
    return False


def _parse_feed_date(entry) -> str | None:
    for key in ("published", "updated", "created"):
        val = entry.get(key)
        if not val:
            continue
        try:
            return _iso(parsedate_to_datetime(val))
        except (TypeError, ValueError):
            pass
    for key in ("published_parsed", "updated_parsed"):
        st = entry.get(key)
        if st:
            try:
                return _iso(datetime(*st[:6], tzinfo=timezone.utc))
            except (TypeError, ValueError):
                pass
    return None


# --- ニュース -----------------------------------------------------------
def fetch_rss(source: dict) -> list[dict]:
    """汎用RSS/Atom取得。"""
    resp = _get(source["url"])
    feed = feedparser.parse(resp.content)
    items = []
    for e in feed.entries:
        summary = clean_text(e.get("summary") or e.get("description") or "")
        img = None
        # メディアサムネイルがあれば拾う
        if e.get("media_thumbnail"):
            img = e["media_thumbnail"][0].get("url")
        elif e.get("media_content"):
            img = e["media_content"][0].get("url")
        elif e.get("links"):
            for lk in e["links"]:
                if lk.get("type", "").startswith("image"):
                    img = lk.get("href")
                    break
        items.append({
            "title": clean_text(e.get("title", ""), limit=200),
            "url": e.get("link", ""),
            "summary": summary,
            "image": img,
            "published": _parse_feed_date(e),
            "source": source["name"],
            "source_id": source["id"],
            "lang": source["lang"],
        })
    return items


def fetch_spaceflightnews(source: dict) -> list[dict]:
    """Spaceflight News API v4。offset でページングして多数取得する。"""
    per_page = source.get("per_page", 50)
    pages = source.get("pages", 1)
    base = source["url"].rstrip("?&")
    items = []
    for page in range(pages):
        url = f"{base}?limit={per_page}&offset={page * per_page}"
        data = None
        # 一時的な失敗（レート制限など）は間を置いて再試行する
        for attempt in range(3):
            try:
                data = _get(url).json()
                break
            except Exception as e:
                if attempt == 2:
                    print(f"    [sfn] page{page} 取得失敗: {type(e).__name__}: {e}",
                          file=sys.stderr)
                else:
                    time.sleep(2 * (attempt + 1))
        if data is None:
            break  # 取得済み分は活かす
        results = data.get("results", [])
        if not results:
            break
        for a in results:
            items.append({
                "title": clean_text(a.get("title", ""), limit=200),
                "url": a.get("url", ""),
                "summary": clean_text(a.get("summary", "")),
                "image": a.get("image_url"),
                "published": a.get("published_at"),
                "source": a.get("news_site") or source["name"],
                "source_id": source["id"],
                "lang": source["lang"],
            })
        if not data.get("next"):
            break
    return items


FETCHERS = {"rss": fetch_rss, "spaceflightnews": fetch_spaceflightnews}


def fetch_news_source(source: dict) -> list[dict]:
    fetcher = FETCHERS.get(source["type"], fetch_rss)
    items = fetcher(source)
    # 総合メディアはAI関連記事だけに絞る
    if source.get("topic_filter"):
        items = [it for it in items if is_ai_related(it)]
    return items


# --- 打ち上げ -----------------------------------------------------------
def fetch_launches() -> list[dict]:
    """Launch Library 2 の打ち上げ（予定＋実績）。言語非依存の生データを返す。"""
    results = []
    for url, upcoming in ((config.LAUNCH_UPCOMING_URL, True),
                          (config.LAUNCH_PREVIOUS_URL, False)):
        try:
            data = _get(url).json()
        except Exception:
            continue  # 片方が落ちてももう片方は活かす
        for r in data.get("results", []):
            r["_upcoming"] = upcoming
            results.append(r)

    launches = []
    for l in results:
        provider = (l.get("launch_service_provider") or {})
        pad = (l.get("pad") or {})
        location = (pad.get("location") or {})
        rocket = ((l.get("rocket") or {}).get("configuration") or {})
        mission = (l.get("mission") or {})
        image = l.get("image")
        if isinstance(image, dict):  # 新APIは dict の場合あり
            image = image.get("image_url") or image.get("thumbnail_url")
        launches.append({
            "id": l.get("id"),
            "name": l.get("name", ""),
            "net": l.get("net"),  # ISO打ち上げ予定時刻(UTC)
            "status": (l.get("status") or {}).get("abbrev") or (l.get("status") or {}).get("name"),
            "status_name": (l.get("status") or {}).get("name"),
            "provider": provider.get("name"),
            "provider_country": provider.get("country_code"),
            "rocket": rocket.get("full_name") or rocket.get("name"),
            "pad": pad.get("name"),
            "location": location.get("name"),
            "country": location.get("country_code"),
            "mission": mission.get("name"),
            "mission_type": mission.get("type"),
            "mission_description": clean_text(mission.get("description", ""), limit=400),
            "image": image,
            "webcast": (l.get("vidURLs") or [{}])[0].get("url") if l.get("vidURLs") else None,
            "upcoming": l.get("_upcoming", True),
        })
    # 予定を先に、実績は新しい順で後ろに
    launches.sort(key=lambda x: (not x["upcoming"],
                                 x["net"] or "" if x["upcoming"] else ""))
    upcoming = [l for l in launches if l["upcoming"]]
    past = sorted([l for l in launches if not l["upcoming"]],
                  key=lambda x: x["net"] or "", reverse=True)
    return upcoming + past


# --- 論文 ---------------------------------------------------------------
def fetch_papers() -> list[dict]:
    """arXiv Atom API。AI関連分野の最新論文。"""
    resp = _get(config.ARXIV_QUERY_URL)
    feed = feedparser.parse(resp.content)
    papers = []
    for e in feed.entries:
        authors = [a.get("name") for a in e.get("authors", []) if a.get("name")]
        pdf = None
        for lk in e.get("links", []):
            if lk.get("title") == "pdf" or lk.get("type") == "application/pdf":
                pdf = lk.get("href")
        cats = [t.get("term") for t in e.get("tags", []) if t.get("term")]
        papers.append({
            "title": clean_text(e.get("title", ""), limit=250),
            "url": e.get("link", ""),
            "pdf": pdf,
            "summary": clean_text(e.get("summary", ""), limit=500),
            "authors": authors[:8],
            "categories": cats[:5],
            "published": _parse_feed_date(e),
        })
    return papers

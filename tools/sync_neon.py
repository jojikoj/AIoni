#!/usr/bin/env python3
"""AIの鬼のデータを Neon（PostgreSQL）へ写す。

⚠️ **これは写しであって正本ではない。** サイトが読むのは今までどおり
   data/*.json と content/articles/*.ja.md のまま。ここが失敗しても
   収集・生成・公開は何ひとつ影響を受けない。
   いきなり正本を移すと、DBが落ちた日にサイトごと止まる。まず写しを作り、
   別のマシンから読み書きできることを確かめてから寄せていく。

写しを持つと何ができるか:
  - 実行機に入らなくてもデータを見られる（今は mini のファイルにしか無い）
  - 別のマシンから直せる（今は git を経由して翌日反映になる）

流すもの:
  data/news.json          → aioni.news        （原文 body_src は写さない）
  content/articles/*.ja.md → aioni.articles
  data/daily_stats.tsv    → aioni.daily_stats

使い方:
  python3 tools/sync_neon.py            # 全部
  python3 tools/sync_neon.py --dry-run  # 何件流すかだけ数える
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path.home() / "claude_AIR/TOEcompany/メディア事業部/共通/運用"))

import neon  # noqa: E402
from aioni.build import news_slug  # noqa: E402

NEWS = ROOT / "data" / "news.json"
STATS = ROOT / "data" / "daily_stats.tsv"
ARTICLES = ROOT / "content" / "articles"


def _iso(raw: str | None):
    """published を datetime にする。読めなければ None（列を空にする）。"""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def news_rows() -> list[dict]:
    try:
        items = json.loads(NEWS.read_text(encoding="utf-8")).get("items", [])
    except (OSError, json.JSONDecodeError) as e:
        print(f"⚠️ news.json を読めません: {e}", file=sys.stderr)
        return []
    rows = []
    for it in items:
        url = (it.get("url") or "").strip()
        if not url:
            continue  # 主キーが無い行は入れない
        rows.append({
            "url": url,
            "title": (it.get("title") or "")[:1000] or "(無題)",
            "title_ja": it.get("title_ja"),
            "summary": it.get("summary"),
            "body_long": it.get("body_long"),
            "source": it.get("source"),
            "lang": it.get("lang"),
            "published": _iso(it.get("published")),
        })
    return rows


def article_rows() -> list[dict]:
    """記事の frontmatter と本文を読む。

    ⚠️ frontmatter は列に切り出すだけでなく**丸ごと**入れる。
       記事は author・order・hero（見出し画像）・image_prompt も持っていて、
       列だけ持っているとDBから戻したときに画像と並び順が失われる。
       「DBから元通りに戻せる」ことが、正本をDBへ移す前提になる。
    """
    rows = []
    for p in sorted(ARTICLES.glob("*.ja.md")):
        meta, body = neon.read_frontmatter(p)
        rows.append({
            "slug": p.name[: -len(".ja.md")],
            "title": meta.get("title") or p.stem,
            "excerpt": meta.get("excerpt"),
            "tag": meta.get("tag"),
            "published": neon.as_date(meta.get("date")),
            "body": body,
            "frontmatter": neon.as_json(meta),
        })
    return rows


def stats_rows() -> list[dict]:
    """daily_stats.tsv を読む。

    列は日によって増えている（途中で「素材」列が入った）ので、
    位置ではなく見出しで対応させる。値は「ニュース3000」のような
    文字列なので数字だけ拾う。
    """
    try:
        lines = STATS.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    if not lines:
        return []
    head = lines[0].split("\t")
    seen: dict[str, dict] = {}
    for line in lines[1:]:
        cells = line.split("\t")
        if not cells or not cells[0].strip():
            continue
        rec = dict(zip(head, cells))
        digits = lambda k: "".join(c for c in rec.get(k, "") if c.isdigit())  # noqa: E731
        try:
            date = datetime.strptime(rec.get("date", "")[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        # 同じ日が複数行あることがある（日次を1日に2回回した日）。後の行で上書きする
        seen[str(date)] = {
            "date": date,
            "news": int(digits("news") or 0),
            "body": int(digits("body") or 0),
            "articles": int(digits("articles") or 0),
        }
    return list(seen.values())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="件数だけ数えて書き込まない")
    args = ap.parse_args()

    news, articles, stats = news_rows(), article_rows(), stats_rows()
    print(f"   対象: ニュース{len(news)}件 / 記事{len(articles)}本 / 日次{len(stats)}日")

    if args.dry_run:
        print("   --dry-run のため書き込みません")
        return 0
    if not (news or articles or stats):
        print("⚠️ 流すものが1件もありません。読み込みに失敗している可能性があります",
              file=sys.stderr)
        return 1

    def build(cur):
        n = neon.upsert(cur, "aioni.news", news, "url")
        a = neon.upsert(cur, "aioni.articles", articles, "slug")
        s = neon.upsert(cur, "aioni.daily_stats", stats, "date")
        return n + a + s

    return neon.run_sync("AIの鬼", build)


if __name__ == "__main__":
    sys.exit(main())

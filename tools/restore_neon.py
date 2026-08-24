#!/usr/bin/env python3
"""Neon から AIの鬼のデータを書き戻す。

## 何のためにあるか

いまDBは「写し」で、正本は実行機のファイル。だが写しのままでは、
**新しい機械で立ち上げるときも、ファイルを失ったときも、DBは役に立たない**。
戻せて初めて写しに意味がある。

そして「戻せること」は、正本をDBへ移す前提そのものでもある。
戻せないうちに正本を移すと、DBが壊れた日に取り返しがつかない。

## 安全のための既定値

**既定では上書きしない。** `--out <dir>` で指定した別の場所に書き出す
（既定は `_restore/`）。中身を見比べて納得してから `--force` で本番へ戻す。
いきなり上書きする作りにすると、検証のつもりが事故になる。

使い方:
  python3 tools/restore_neon.py                  # _restore/ に書き出して比べる
  python3 tools/restore_neon.py --out /tmp/x
  python3 tools/restore_neon.py --force          # data/ と content/ を直接上書き
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path.home() / "claude_AIR/TOEcompany/メディア事業部/共通/運用"))

import neon  # noqa: E402

# frontmatter に書き戻す順番。
#
# jsonb はキーの並びを保たないので、戻すときにこちらで決め直す必要がある。
# 順番が違っても意味は同じ（ビルドは辞書として読む）が、揃えておかないと
# 全記事に git の差分が出て、本当の変更が埋もれる。
#
# 実際の記事256本を数えて、平均の出現位置が早い順に並べたもの。
# ここに無いキーは後ろにまとめて出す（新しい項目が増えても落とさない）。
FM_ORDER = ["title", "seo_title", "excerpt", "meta_desc", "tag", "author",
            "date", "updated", "order", "hero", "image_prompt"]


def write_articles(cur, out: Path) -> int:
    cur.execute("select slug, body, frontmatter from aioni.articles order by slug")
    rows = cur.fetchall()
    d = out / "content" / "articles"
    d.mkdir(parents=True, exist_ok=True)
    n = 0
    for slug, body, fm in rows:
        fm = fm or {}
        keys = [k for k in FM_ORDER if k in fm] + [k for k in fm if k not in FM_ORDER]
        # 末尾の "" が2つあるのは、frontmatter の閉じ `---` と本文のあいだの
        # 空行を作るため。1つだと元のファイルと1行ずれて、差分が全件に出る。
        lines = ["---"] + [f"{k}: {fm[k]}" for k in keys] + ["---", "", ""]
        (d / f"{slug}.ja.md").write_text("\n".join(lines) + (body or ""), encoding="utf-8")
        n += 1
    return n


def write_news(cur, out: Path) -> int:
    cur.execute("""select url, title, title_ja, summary, body_long, source, lang, published
                   from aioni.news order by published desc nulls last""")
    items = []
    for url, title, title_ja, summary, body_long, source, lang, published in cur.fetchall():
        it = {"title": title, "url": url, "summary": summary,
              "published": published.isoformat() if published else None,
              "source": source, "lang": lang}
        if title_ja:
            it["title_ja"] = title_ja
        if body_long:
            it["body_long"] = body_long
        items.append({k: v for k, v in it.items() if v is not None})
    d = out / "data"
    d.mkdir(parents=True, exist_ok=True)
    # ⚠️ body_src（記事の原文）はDBに入れていない。解説を作り終えれば不要になる
    #    中間物なので写していない。戻したファイルにも入らないが、次の収集で
    #    新しい記事のぶんだけ取り直される。過去分は戻らない（戻す必要もない）。
    (d / "news.json").write_text(
        json.dumps({"generated_at": None, "count": len(items), "items": items},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return len(items)


def write_stats(cur, out: Path) -> int:
    cur.execute("select date, news, body, articles from aioni.daily_stats order by date")
    rows = cur.fetchall()
    d = out / "data"
    d.mkdir(parents=True, exist_ok=True)
    lines = ["date\tnews\tbody\tarticles"]
    for date, news, body, articles in rows:
        lines.append(f"{date}\tニュース{news}\t本文{body}\t記事{articles}")
    (d / "daily_stats.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="書き出し先（既定 _restore/）")
    ap.add_argument("--force", action="store_true",
                    help="data/ と content/ を直接上書きする")
    args = ap.parse_args()

    if args.force and args.out:
        print("--force と --out は同時に使えません", file=sys.stderr)
        return 1
    out = ROOT if args.force else Path(args.out or (ROOT / "_restore"))
    if args.force:
        print("⚠️ 本番のファイルを上書きします")

    try:
        conn = neon.connect()
    except Exception as e:
        print(f"⚠️ Neon に接続できません: {e}", file=sys.stderr)
        return 1
    if conn is None:
        print(f"接続先が未設定です（{neon.URL_FILE}）", file=sys.stderr)
        return 1

    try:
        with conn.cursor() as cur:
            a = write_articles(cur, out)
            n = write_news(cur, out)
            s = write_stats(cur, out)
    except Exception as e:
        print(f"⚠️ 書き戻しに失敗しました: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    print(f"   記事{a}本 / ニュース{n}件 / 日次{s}日 を {out} に書き戻しました")
    if not args.force:
        print(f"   本番と見比べる: diff -rq {out}/content/articles {ROOT}/content/articles")
    return 0


if __name__ == "__main__":
    sys.exit(main())

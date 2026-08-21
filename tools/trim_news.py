#!/usr/bin/env python3
"""役目を終えた原文(body_src)を news.json から落として、ファイルの肥大を止める。

data/news.json は毎日そのまま git にコミットされる。1回あたり15MB前後あり、
57コミットで .git が1.2GB まで膨らんでいた。放置すると年間で数GB増え続ける。

⚠️ 減らしてよいのは「中身」であって「件数」ではない。
   NEWS_LIMIT=3000 は 2026-08-01 に 600 から引き上げた設定で、
   上限を超えた記事は news.json から押し出され /news/<slug>/ ごと消える。
   600 だった頃は検索表示のあった237ページのうち96ページ(表示の32%)が
   404になっていた。件数は絶対に触らないこと。

そこで body_src を落とす。実測(2026-08-21)で news.json 15.7MB のうち
body_src が 9.7MB = 64.5% を占めていた。この項目は:

  - サイトには一度も表示されない（テンプレートが読むのは body_long）
  - 解説生成 gen_news_summaries.py の素材。生成が済めば用済み
  - 旬ネタ記事 trend_news.py / publish_daily.py の素材。ただしこれらは
    「その日に収集したニュースからその日に書く」設計なので、古い分は使わない

よって「解説(body_long)が生成済み」かつ「公開から --days 日以上経った」記事の
body_src だけを消す。解説がまだ無い記事は素材として必要なので残す
（消すと二度と生成できなくなる）。body_ja は build.py が読むので触らない。

使い方:
  python3 tools/trim_news.py --dry-run      # 何がどれだけ減るか見るだけ
  python3 tools/trim_news.py                # 既定の7日で実行
  python3 tools/trim_news.py --days=14      # もっと長く残す
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

NEWS_PATH = Path(__file__).resolve().parent.parent / "data" / "news.json"

# 何日分の原文を手元に残すか。
# trend_news.py が使うのは当日分だけなので7日でも余裕があるが、
# 収集や生成が数日止まった場合に素材ごと失わないよう1週間を既定にする。
DEFAULT_DAYS = 7


def _published_at(item: dict) -> datetime | None:
    """published を UTC の datetime にする。読めなければ None（＝消さない）。"""
    raw = (item.get("published") or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    # タイムゾーンが無い表記が混ざることがある。UTC とみなす
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS,
                    help=f"原文を残す日数（既定 {DEFAULT_DAYS}）")
    ap.add_argument("--dry-run", action="store_true",
                    help="書き込まず、削減量だけ表示する")
    args = ap.parse_args()

    if not NEWS_PATH.exists():
        print(f"news.json が見つかりません: {NEWS_PATH}", file=sys.stderr)
        return 1
    try:
        data = json.loads(NEWS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"news.json を読めません: {e}", file=sys.stderr)
        return 1

    items = data.get("items")
    if not isinstance(items, list):
        print("news.json に items がありません。何もしません", file=sys.stderr)
        return 1

    before = NEWS_PATH.stat().st_size
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)

    trimmed = 0          # 実際に落とした件数
    freed = 0            # 落としたバイト数
    kept_no_long = 0     # 解説がまだ無いので残した件数
    kept_recent = 0      # 新しいので残した件数
    kept_undated = 0     # 日付が読めないので残した件数

    for it in items:
        src = it.get("body_src")
        if not src:
            continue
        if not it.get("body_long"):
            kept_no_long += 1
            continue
        pub = _published_at(it)
        if pub is None:
            kept_undated += 1
            continue
        if pub > cutoff:
            kept_recent += 1
            continue
        freed += len(json.dumps(src, ensure_ascii=False).encode())
        del it["body_src"]
        # 文字数の記録だけ残す（後から「原文があった」ことが分かるように）
        it.setdefault("body_chars", len(src))
        trimmed += 1

    print(f"原文を落とした      : {trimmed:5d}件 ({freed / 1048576:.2f}MB)")
    print(f"残した(解説がまだ無い): {kept_no_long:5d}件  ← 素材として必要")
    print(f"残した({args.days}日以内)  : {kept_recent:5d}件")
    if kept_undated:
        print(f"残した(日付が読めない): {kept_undated:5d}件")

    if args.dry_run:
        print("--dry-run のため書き込みません")
        return 0
    if not trimmed:
        print("落とすものがないので書き込みません")
        return 0

    # 書き込みは一時ファイル→置換。途中で落ちても news.json を壊さない
    tmp = NEWS_PATH.with_suffix(".json.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(NEWS_PATH)
    except OSError as e:
        print(f"書き込みに失敗しました: {e}", file=sys.stderr)
        tmp.unlink(missing_ok=True)
        return 1

    after = NEWS_PATH.stat().st_size
    print(f"news.json {before / 1048576:.2f}MB → {after / 1048576:.2f}MB "
          f"({(before - after) / before * 100:.0f}%減)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

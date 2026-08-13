#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIの鬼｜今週のニュースから「書くべきネタ」を選ぶ。

trend_intake.py（Googleサジェスト起点）との違いは、ネタ元が「検索語」ではなく
**この1週間に実際に起きたこと**であること。

サジェストは「ai エージェント とは」のような定常的な検索意図しか返さない。
それは旬ではないし、既に226本ある記事とカニバる。一方 news.json には
毎日80〜90件の実ニュースが入り、本文（body_src）と解説（body_long）まで
付いている。旬はこちらにしかない。

出力は2つ:
  1) _旬ネタ/今週.md  … 人が読んで「どれを実測するか」を決めるための一覧
  2) --json           … 週次まとめ記事の素材（gen_weekly_ai.py が使う）

  python3 tools/trend_news.py              # 今週.md を更新
  python3 tools/trend_news.py --days 7     # 対象期間を変える
  python3 tools/trend_news.py --json       # 素材をJSONで標準出力
"""
from __future__ import annotations
import json, sys, re, pathlib, datetime, argparse, collections

ROOT = pathlib.Path(__file__).resolve().parent.parent
NEWS = ROOT / "data" / "news.json"
ARTICLES_DIR = ROOT / "content" / "articles"
OUT = ROOT / "_旬ネタ" / "今週.md"

# 中小企業の実務家にとって「何かが変わる」ニュースを上に出すための重み。
# モデルが賢くなった話より、使えるようになった/安くなった/危なくなった話を上に出す。
WEIGHTS = {
    3: ["値下げ", "無料化", "無料プラン", "料金", "価格", "コスト", "提供開始", "一般提供",
        "日本語対応", "国内提供", "中小企業", "製造業", "情報漏", "流出", "脆弱性",
        "規制", "法規制", "ガイドライン", "義務化"],
    2: ["リリース", "公開", "発表", "アップデート", "新モデル", "エージェント", "自動化",
        "オープンソース", "ローカル", "オンプレ", "セキュリティ", "障害", "停止", "訴訟",
        "業務", "現場"],
    1: ["ベンチマーク", "性能", "精度", "研究", "論文", "調達", "資金"],
}
# 出どころが自社の宣伝でしかないものは落とす
_NOISE = ["PR TIMES", "プレスリリース配信"]
# 記事の体裁をした告知。ニュースではないので拾わない。
# （「無料」を加点語にしていたら「無料レポート進呈」「無料で読めるITまんが」が
#   上位に来た。読者にとって“何かが変わった”わけではない。）
_AD = ["無料レポート", "無料ダウンロード", "ホワイトペーパー", "ウェビナー", "セミナー",
       "参加者募集", "申込受付", "プレゼント", "まんが", "マンガ", "キャンペーン",
       "提供開始のお知らせ", "アンケート調査"]

# AIの鬼のコーナー。どれに当てはめるかで書き方が変わる。
def _corner(title: str, body: str) -> str:
    blob = title + body[:300]
    if any(w in blob for w in ("値下げ", "料金", "価格", "無料", "コスト", "提供開始", "日本語対応")):
        return "解説（すぐ効く変化）"
    if any(w in blob for w in ("情報漏", "流出", "脆弱性", "規制", "訴訟", "障害", "停止", "義務")):
        return "中の鬼（リスクの読み物）"
    if any(w in blob for w in ("エージェント", "自動化", "業務", "現場", "中小企業", "ローカル", "オンプレ")):
        return "実践室（TOEで実測できる）"
    return "解説"


def _score(item: dict) -> int:
    blob = f"{item.get('title_ja') or item.get('title','')}{(item.get('summary_ja') or '')[:200]}"
    s = 0
    for w, words in WEIGHTS.items():
        s += w * sum(1 for k in words if k in blob)
    if (item.get("body_long") or "").strip():
        s += 2                     # 解説済み＝日次パイプラインが拾った重要ニュース
    if (item.get("body_src") or "").strip():
        s += 2                     # 原文がある＝濃く書ける
    return s


def _existing_titles() -> list[str]:
    out = []
    for md in ARTICLES_DIR.glob("*.ja.md"):
        m = re.search(r"^title:\s*(.+)$", md.read_text(encoding="utf-8"), re.M)
        if m:
            out.append(m.group(1).strip())
    return out


def _norm(s: str) -> str:
    return re.sub(r"[\s　\-—・:：|｜]+", "", s or "").lower()


def _covered(title: str, existing: list[str]) -> bool:
    """既存記事と主要語が重なるか（同じ話を二度書かない）。"""
    words = [w for w in re.split(r"[\s　、。・]+", title) if len(w) >= 3][:4]
    if not words:
        return False
    joined = _norm("".join(existing))
    hit = sum(1 for w in words if _norm(w) in joined)
    return hit >= max(2, len(words) - 1)


def pick(days: int = 7, limit: int = 12) -> list[dict]:
    data = json.loads(NEWS.read_text(encoding="utf-8"))
    items = data.get("items", data if isinstance(data, list) else [])
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    existing = _existing_titles()

    cands = []
    for it in items:
        pub = (it.get("published") or "")[:10]
        if not pub or pub < since:
            continue
        src = it.get("source") or ""
        if any(n in src for n in _NOISE):
            continue
        title = (it.get("title_ja") or it.get("title") or "").strip()
        if len(title) < 8:
            continue
        if any(w in title for w in _AD):
            continue
        sc = _score(it)
        if sc < 4:                       # 拾う価値のない小ネタを落とす
            continue
        cands.append({
            "title": title,
            "url": it.get("url", ""),
            "source": src,
            "published": pub,
            "score": sc,
            "body_long": (it.get("body_long") or "").strip(),
            "has_src": bool((it.get("body_src") or "").strip()),
            "corner": _corner(title, it.get("summary_ja") or ""),
        })

    cands.sort(key=lambda x: (-x["score"], x["published"]))

    # 同じ出来事の重複報道を1本に束ねる（先頭3語が同じなら同一とみなす）
    seen, out = set(), []
    for c in cands:
        key = _norm(c["title"])[:12]
        if key in seen or _covered(c["title"], existing):
            continue
        seen.add(key)
        out.append(c)
        if len(out) >= limit:
            break
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--limit", type=int, default=12)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    picks = pick(a.days, a.limit)
    if a.json:
        print(json.dumps(picks, ensure_ascii=False, indent=1))
        return 0

    today = datetime.date.today()
    by_corner = collections.OrderedDict()
    for p in picks:
        by_corner.setdefault(p["corner"], []).append(p)

    lines = [f"# AIの鬼｜今週書くネタ（{today} 時点・直近{a.days}日）", "",
             "> 実測は捏造禁止・人が書く。ここは「今週実際に起きたこと」から候補を出すところまで。",
             f"> 候補{len(picks)}件。原文が取れているものは【原文あり】＝濃く書ける。", ""]
    for corner, rows in by_corner.items():
        lines += [f"## {corner}", "", "| 旬度 | 見出し | 出どころ | 原文 |", "|---|---|---|---|"]
        for r in rows:
            heat = "🔥🔥🔥" if r["score"] >= 12 else "🔥🔥" if r["score"] >= 8 else "🔥"
            t = r["title"].replace("|", "／")[:60]
            lines.append(f"| {heat} | [{t}]({r['url']}) | {r['source'][:18]} | "
                         f"{'原文あり' if r['has_src'] else '見出しのみ'} |")
        lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[trend_news] 候補{len(picks)}件 → {OUT}")
    for p in picks[:8]:
        print(f"  {p['score']:>3}点 [{p['corner']}] {p['title'][:52]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

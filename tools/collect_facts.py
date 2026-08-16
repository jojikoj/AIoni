"""当社の実測を、実ファイルから毎日集めて素材にする。

なぜ作ったか（2026-08-16）:
    商用クエリ（仕事につながる検索語）で記事を自動生成させたところ、
    4件中3件が「素材が無い」と自ら見送った。理由はどれも同じで、
    publish_daily.py の FACTS が **AI検索の可視性測定に偏った固定文字列**
    だったため。「ai研修 法人 選定」「生成ai 開発会社」に答える数字が
    1行も無く、書こうとすると一般論になる（＝書かないのが正しい）。

    今後、人は記事を書かない。だとすれば素材は自動で増やすしかない。
    幸い、**このサイト自身の運用が当社最大の一次情報**になっている。
    AIで記事を毎日生成し、3,000件のニュースを自動収集し、それが検索で
    どうなったかを毎日測っている会社は多くない。数字はすべて実ファイルにある。

    ここで集めた事実は data/facts_auto.md に書き出し、記事生成が読む。
    固定の FACTS（人が確かめた外部調査・過去の実測）と併用する。

集める先（すべて当社の実ファイル。外から数字を持ち込まない）:
    - data/gsc_history.tsv    … 検索の実測（表示・クリック・順位）
    - data/gsc_sections.tsv   … セクション別の内訳
    - data/daily_stats.tsv    … 収集件数・要約件数・記事本数
    - content/articles/*.md   … コーナー別の本数・字数・公開日
    - claude_AIR/…/ログ        … 3媒体の日次の成否

実行:
    python3 tools/collect_facts.py          # data/facts_auto.md を更新
    python3 tools/collect_facts.py --print  # 標準出力に出すだけ
"""
from __future__ import annotations

import collections
import datetime
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
HOME = pathlib.Path.home()
ARTICLES = ROOT / "content" / "articles"
HISTORY = ROOT / "data" / "gsc_history.tsv"
SECTIONS = ROOT / "data" / "gsc_sections.tsv"
STATS = ROOT / "data" / "daily_stats.tsv"
OUT = ROOT / "data" / "facts_auto.md"
MEDIA_LOGS = {
    "AIの鬼": HOME / "claude_AIR/TOEcompany/コンテンツ部/案件/AIの鬼/ログ",
    "補助金の鬼": HOME / "claude_AIR/TOEcompany/メディア事業部/補助金の鬼/更新ログ",
    "UchUchU": HOME / "claude_AIR/TOEcompany/メディア事業部/案件/UchUchU/ログ",
}


def tsv(path: pathlib.Path) -> list[list[str]]:
    if not path.exists():
        return []
    return [l.split("\t") for l in
            path.read_text(encoding="utf-8").splitlines()[1:] if l.strip()]


def search_facts() -> list[str]:
    rows = tsv(HISTORY)
    if not rows:
        return []
    out = []
    if len(rows) >= 7:
        cur = rows[-7:]
        imp = sum(int(r[1]) for r in cur)
        clk = sum(int(r[2]) for r in cur)
        out.append(f"- 当サイトの直近7日（{cur[0][0]}〜{cur[-1][0]}）は"
                   f"検索表示{imp}回・クリック{clk}回。")
    if len(rows) >= 28:
        m = rows[-28:]
        imp = sum(int(r[1]) for r in m)
        clk = sum(int(r[2]) for r in m)
        ctr = clk / imp * 100 if imp else 0
        out.append(f"- 直近28日は表示{imp}回・クリック{clk}回（CTR {ctr:.1f}%）。")
    if len(rows) >= 14:
        cur, prev = rows[-7:], rows[-14:-7]
        ci = sum(int(r[1]) for r in cur)
        pi = sum(int(r[1]) for r in prev)
        d = (ci - pi) / pi * 100 if pi else 0
        out.append(f"- 前の7日と比べた表示の増減は {d:+.0f}%。")
    sec = tsv(SECTIONS)
    if sec:
        r = sec[-1]
        if len(r) >= 9:
            out.append(f"- {r[0]}時点の内訳（直近28日）: "
                       f"自社記事 表示{r[1]}回・クリック{r[2]}回 / "
                       f"集約ニュース 表示{r[3]}回・クリック{r[4]}回 / "
                       f"論文 表示{r[5]}回・クリック{r[6]}回。")
    return out


def production_facts() -> list[str]:
    rows = tsv(STATS)
    out = []
    if rows:
        last = rows[-1]
        nums = [re.sub(r"[^0-9]", "", c) for c in last[1:]]
        labels = ["収集済みニュース", "自社要約つきニュース", "本文取得済み", "記事"]
        parts = [f"{lab}{n}件" for lab, n in zip(labels, nums) if n]
        if parts:
            out.append(f"- {last[0]}時点の生産量: " + " / ".join(parts) + "。"
                       "収集も要約も記事も、人手を介さず毎日自動で動いている。")
    if len(rows) >= 8:
        first, last = rows[-8], rows[-1]
        try:
            d0 = int(re.sub(r"[^0-9]", "", first[-1]))
            d1 = int(re.sub(r"[^0-9]", "", last[-1]))
            out.append(f"- 直近7日で記事は{d0}本から{d1}本へ増えた"
                       f"（1日あたり約{(d1 - d0) / 7:.1f}本）。")
        except (ValueError, IndexError):
            pass
    return out


def article_facts() -> list[str]:
    today = datetime.date.today()
    by_tag: dict[str, list] = collections.defaultdict(list)
    ages = []
    for p in ARTICLES.glob("*.ja.md"):
        t = p.read_text(encoding="utf-8")
        tag = re.search(r"^tag:\s*(.+)$", t, re.M)
        d = re.search(r"^date:\s*['\"]?(\d{4}-\d{2}-\d{2})", t, re.M)
        body = re.sub(r"^---\n.*?\n---\n", "", t, flags=re.S)
        chars = len(re.sub(r"\s", "", body))
        if tag:
            by_tag[tag.group(1).strip()].append(chars)
        if d:
            ages.append((today - datetime.date.fromisoformat(d.group(1))).days)
    out = []
    total = sum(len(v) for v in by_tag.values())
    if total:
        parts = [f"{k}{len(v)}本" for k, v in
                 sorted(by_tag.items(), key=lambda z: -len(z[1]))]
        out.append(f"- 記事は全{total}本（{' / '.join(parts)}）。")
        avg = sum(sum(v) for v in by_tag.values()) / total
        out.append(f"- 1本あたりの平均字数は約{avg:.0f}字。")
    if ages:
        young = sum(1 for a in ages if a <= 30)
        out.append(f"- {len(ages)}本のうち{young}本"
                   f"（{young / len(ages) * 100:.0f}%）は公開30日以内。"
                   "サイト自体がまだ若い。")
    return out


def ops_facts() -> list[str]:
    """日次が実際に回っているか。

    ⚠️ ログファイルの日付で判断しない。実行機（Mac mini）のログは
    claude_AIR に同期されておらず、このMacから見ると18日前で止まって
    見えるが、実際には毎日動いている（daily_stats.tsv が伸びている）。
    「見えない＝止まっている」と書くと、そのまま記事の嘘になる。
    稼働の判定は成果物の更新日で行う。
    """
    rows = tsv(STATS)
    if not rows:
        return []
    last_date = rows[-1][0]
    try:
        age = (datetime.date.today()
               - datetime.date.fromisoformat(last_date)).days
    except ValueError:
        return []
    days = len({r[0] for r in rows})
    out = [f"- 日次の自動更新は{days}日分の記録があり、最後に動いたのは"
           f"{last_date}（{age}日前）。"]
    if age <= 1:
        out.append("- 現在も毎日止まらずに回っている。")
    return out


def build() -> str:
    L = ["【当社（株式会社TOE / AIの鬼）の自動収集した実測",
         f"（{datetime.date.today()} 更新。すべて当社の実ファイルから機械的に集計）】",
         ""]
    for title, facts in [("検索の実測", search_facts()),
                         ("生産量（自動化の実績）", production_facts()),
                         ("記事の構成", article_facts()),
                         ("自社メディアの運用", ops_facts())]:
        if facts:
            L.append(f"■ {title}")
            L.extend(facts)
            L.append("")
    L.append("※ この節の数字は当社サイトの実データから自動集計したもので、")
    L.append("  外部の推計や業界平均ではありません。")
    return "\n".join(L)


def main() -> int:
    text = build()
    if "--print" in sys.argv:
        print(text)
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"   自社実測を更新: {OUT.name}（{len(text)}字）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

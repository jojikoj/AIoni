"""毎日の実測レビュー。Search Console の実績から「次に直す1件」を出す。

なぜ作ったか（2026-08-15）:
    日次（tools/daily.sh）は 収集 → 解説 → 記事1本 → ビルド → 公開 で、
    **作る工程しか無かった**。効いたかどうかを測る工程がどこにも無く、
    Search Console は7/21・7/29・7/30・8/13の4回、人が手で叩いただけ。
    その結果、記事を205本から238本（+16%）に増やした3週間で表示は
    139/日（7/30）→ 80/日（8/12）と横ばい〜微減、という状態に
    誰も気づかないまま量産が続いた。
    朝9時の seo-daily.mjs は「規格違反（title過長・description欠落）」を
    直す仕組みで、これは設計通り正しい。だが規格が正しくても順位も
    クリックも増えない、という今回の症状はそこでは原理的に検知できない。

    作る仕組みだけ自動化して、測る仕組みを人の手作業のまま残したのが原因。
    ここでその片側を埋める。

見るもの（すべて実測。推測で並べない）:
    1. 共食い  … 同じ検索語で自社の複数ページが競合している。
                 実測でこれが一番効いていた。「kimi k3 使い方」は
                 ニュース要約ページが1.9位・24表示・クリック0を占め、
                 本物の解説記事 /articles/kimi-k3-how-to-use/ が
                 表に出られていなかった。
    2. 惜しい  … 1ページ目なのにクリック0。順位ではなくタイトルの問題。
    3. あと一歩… 11〜20位。加筆と内部リンクで1ページ目に入りうる。
    4. 沈黙    … 公開から2週間以上たっても表示がほぼ0の自社記事。
                 増やすより、統合するか書き直す対象。
    5. 推移    … 前週比。増えているのか減っているのかを毎日残す。

直さない:
    ここは提案までで、修正は自動でしない（[[feedback_measure_before_fixing]]）。
    施策を毎日あちこち打つと、順位が動いた理由を追えなくなる。
    1日1系統、人が決めて打つ。このレポートはその「決める材料」を出す係。

出力:
    - data/gsc_history.tsv       … 日次の実測を1行ずつ積む（推移の土台）
    - claude_AIR/…/AIの鬼/実測レビュー/YYYY-MM-DD.md … 人が読む
    - 標準出力に要約（日次ログに残る）

実行:
    python3 tools/daily_review.py            # ai-oni.com
    python3 tools/daily_review.py --days=28
"""
from __future__ import annotations

import collections
import datetime
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = "sc-domain:ai-oni.com"
HOME = pathlib.Path.home()
OUT_DIR = HOME / "claude_AIR/TOEcompany/コンテンツ部/案件/AIの鬼/実測レビュー"
HISTORY = ROOT / "data" / "gsc_history.tsv"
# 実測で拾えている検索語。翌日の記事づくり（publish_daily.py）が読む。
# 測った結果を作る側に戻すための受け渡し口。ここが無かったので、
# 毎日書く記事のテーマが検索需要とまったく無関係に決まっていた。
QUERIES = ROOT / "data" / "gsc_queries.json"
# セクション別の推移。2026-08-15 にニュース個別1,187ページを noindex に
# したので、その賭けが当たったかを判定するための土台。
# 判定基準: /articles/ の表示が増えれば成功（ニュースが退いて自社記事が
# 繰り上がった）。変わらないか減れば、あの施策は表示を捨てただけになる。
SECTIONS = ROOT / "data" / "gsc_sections.tsv"
ARTICLES = ROOT / "content" / "articles"

# Search Console のデータは2〜3日遅れて確定する。直近2日は見ない。
LAG_DAYS = 2
# 「沈黙」と判定するまでの猶予。公開直後はインデックスされていないだけ。
SILENT_AFTER_DAYS = 14


def fetch(days: int) -> tuple[list, list, list, str, str]:
    """GSC から page×query / date / page を取る。認証が無ければ例外。"""
    import google.auth
    from googleapiclient.discovery import build

    cred, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/webmasters.readonly"])
    svc = build("searchconsole", "v1", credentials=cred, cache_discovery=False)
    end = datetime.date.today() - datetime.timedelta(days=LAG_DAYS)
    start = end - datetime.timedelta(days=days - 1)

    def q(dims, limit=5000, s=start, e=end):
        rows = svc.searchanalytics().query(siteUrl=SITE, body={
            "startDate": str(s), "endDate": str(e),
            "dimensions": dims, "rowLimit": limit}).execute().get("rows", [])
        return rows

    pq = q(["page", "query"])
    daily = q(["date"], limit=1000)
    pages = q(["page"])
    return pq, daily, pages, str(start), str(end)


def short(url: str) -> str:
    return url.replace("https://ai-oni.com/", "/")


def noindexed() -> set[str]:
    """いまのビルドで noindex にしているページ。

    Search Console の実績は2〜3日前までの過去で、noindex が実際に効くまでは
    数週間かかる。その間、既に手を打ったページが毎日「機会」として出続けると、
    同じ指摘を無視する習慣がつき、レポートが読まれなくなる。
    ビルド済みの dist を見て、対処済みのものは提案から外す。
    """
    dist = ROOT / "dist"
    out: set[str] = set()
    if not dist.exists():
        return out
    for html in dist.rglob("index.html"):
        try:
            head = html.read_text(encoding="utf-8", errors="ignore")[:8000]
        except OSError:
            continue
        if "noindex" in head:
            rel = html.relative_to(dist).parent.as_posix()
            out.add("/" if rel == "." else f"/{rel}/")
    return out


def find_cannibals(pq: list) -> list[dict]:
    """同じ検索語に自社の2ページ以上が出ている組を、損失の大きい順に返す。

    損失＝「上位に出ているのにクリックを取れていないページ」の表示回数。
    ニュース要約ページが自社記事の前に立っている型を、ここで毎日捕まえる。
    """
    by_query: dict[str, list] = collections.defaultdict(list)
    for r in pq:
        by_query[r["keys"][1]].append(r)
    out = []
    for query, rows in by_query.items():
        if len(rows) < 2:
            continue
        rows.sort(key=lambda z: z["position"])
        top = rows[0]
        # 先頭がクリックを取れていない場合だけ問題にする。
        # 取れているなら競合していても実害がない。
        if top["clicks"] > 0:
            continue
        # 圏外（20位より下）同士の競合は実害が無い。誰も見ていない場所で
        # 順番を争っても、直したところで戻ってくるクリックが無い。
        if top["position"] > 20.0:
            continue
        others = rows[1:]
        out.append({
            "query": query,
            "top": short(top["keys"][0]),
            "top_pos": top["position"],
            "top_imp": top["impressions"],
            "rivals": [(short(o["keys"][0]), o["position"]) for o in others],
            "loss": top["impressions"],
        })
    out.sort(key=lambda z: -z["loss"])
    return out


def find_near_miss(pq: list) -> tuple[list, list]:
    """(1ページ目なのにクリック0, 11〜20位であと一歩) を返す。"""
    first = [r for r in pq if r["position"] <= 10.0
             and r["impressions"] >= 3 and r["clicks"] == 0]
    first.sort(key=lambda z: -z["impressions"])
    second = [r for r in pq if 10.0 < r["position"] <= 20.0
              and r["impressions"] >= 2]
    second.sort(key=lambda z: -z["impressions"])
    return first, second


# 仕事につながる検索語かどうか。ここに当たる語は、表示が少なくても
# 順位が低くても、優先して記事を用意する価値がある。
# 読み物として当たっても受注にはつながらないので、通常の機会とは分けて出す。
COMMERCIAL = (
    "研修", "見積", "費用", "料金", "価格", "相場", "導入", "選び方", "選定",
    "比較", "おすすめ", "外注", "委託", "開発会社", "ベンダー", "業者",
    "コンサル", "支援", "代行", "補助金", "助成金", "事例", "失敗",
    "中小企業", "製造業", "工場", "総務", "経理", "人事",
)


def find_commercial(pq: list) -> list[dict]:
    """仕事につながる検索語で、当社が見えていないもの。

    順位80位でも表示が出ているということは、その語を検索する人が
    実際にいて、Google が当社を候補として認識しているということ。
    ここは「書けば取れる可能性がある需要」であって、
    表示回数の大小で切ってはいけない（大きくなってからでは遅い）。
    """
    agg: dict[str, dict] = {}
    for r in pq:
        q = r["keys"][1]
        if not any(w in q for w in COMMERCIAL):
            continue
        a = agg.setdefault(q, {"query": q, "imp": 0, "clicks": 0,
                               "pos": [], "pages": set()})
        a["imp"] += r["impressions"]
        a["clicks"] += r["clicks"]
        a["pos"].append(r["position"])
        a["pages"].add(short(r["keys"][0]))
    out = []
    for a in agg.values():
        a["best"] = min(a["pos"])
        a["pages"] = sorted(a["pages"])[:2]
        out.append(a)
    # 順位が悪いほど＝まだ取れていないほど上に出す。表示が同じなら順位順。
    out.sort(key=lambda z: (-z["imp"], z["best"]))
    return out


def save_queries(pq: list, commercial: list) -> None:
    """実測で拾えている検索語を、記事づくり側へ渡す。

    ここが無かったために、毎日1本書く記事のテーマが「その日のニュース」
    だけで決まり、検索需要と一度も突き合わされていなかった。
    実測では238本中160本が公開2週間を過ぎても表示ほぼ0のままで、
    「AEOとは何か」のように、そもそも誰も検索しない言葉の記事が積まれていた。
    """
    agg: dict[str, dict] = {}
    for r in pq:
        q = r["keys"][1]
        a = agg.setdefault(q, {"query": q, "imp": 0, "clicks": 0, "pos": 999.0})
        a["imp"] += r["impressions"]
        a["clicks"] += r["clicks"]
        a["pos"] = min(a["pos"], r["position"])
    ranked = sorted(agg.values(), key=lambda z: -z["imp"])
    QUERIES.write_text(json.dumps({
        "updated": str(datetime.date.today()),
        # 表示が出ている＝Google が当社を候補として認識している語。
        "seen": [{"q": a["query"], "imp": round(a["imp"]),
                  "clicks": round(a["clicks"]), "pos": round(a["pos"], 1)}
                 for a in ranked[:60]],
        # そのうち仕事につながる語。記事のテーマとして最優先。
        "commercial": [{"q": a["query"], "imp": round(a["imp"]),
                        "pos": round(a["best"], 1)} for a in commercial[:30]],
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def find_silent(pages: list) -> list[tuple[str, int, str]]:
    """公開から日が経っているのに表示がほぼ無い自社記事。"""
    seen = {short(r["keys"][0]).strip("/").replace("articles/", ""): r["impressions"]
            for r in pages if "/articles/" in r["keys"][0]}
    today = datetime.date.today()
    out = []
    for md in sorted(ARTICLES.glob("*.ja.md")):
        slug = md.name.replace(".ja.md", "")
        text = md.read_text(encoding="utf-8")
        m = re.search(r"^date:\s*['\"]?(\d{4}-\d{2}-\d{2})", text, re.M)
        if not m:
            continue
        pub = datetime.date.fromisoformat(m.group(1))
        age = (today - pub).days
        if age < SILENT_AFTER_DAYS:
            continue
        imp = seen.get(slug, 0)
        if imp <= 1:
            title = ""
            tm = re.search(r"^title:\s*(.+)$", text, re.M)
            if tm:
                title = tm.group(1).strip().strip("'\"")
            out.append((slug, age, title))
    return out


def append_sections(pages: list) -> str:
    """セクション別の表示・クリックを日々積む。

    2026-08-15 に打った施策（ニュース個別1,187ページを noindex）の
    答え合わせに使う。あの日の判断は「共食いを解消して自社記事を前に出す」
    というものだったが、後から数え直すと共食いは171クエリ中4件、
    実害のあるものは1件だけで、**根拠は薄かった**。
    一方で確実に失うのは表示の66%（ニュース個別だけが出ていた129クエリ・
    476表示・11クリック）。失うクリックの中身は「google 人事異動」
    「minimax h3 colab」など他社プロダクトの指名検索で、受注価値は無い。

    つまりこれは「価値の無い実績を捨てて、自社記事の繰り上がりに賭けた」判断。
    賭けなので、当たったかを測れるようにしておく。

      成功 … /articles/ の表示が増える（ニュースが退いた枠に入った）
      失敗 … /articles/ が横ばい以下（表示を捨てただけ）

    判定は4週間後（2026-09-12 前後）。noindex が効くまで数週間かかるため。
    """
    agg: dict[str, list[float]] = collections.defaultdict(lambda: [0.0, 0.0])
    for r in pages:
        seg = short(r["keys"][0]).strip("/").split("/")[0] or "(top)"
        if seg not in ("news", "articles", "papers"):
            seg = "other"
        agg[seg][0] += r["impressions"]
        agg[seg][1] += r["clicks"]
    today = str(datetime.date.today())
    line = "\t".join([today] + [
        f"{agg[s][0]:.0f}\t{agg[s][1]:.0f}"
        for s in ("articles", "news", "papers", "other")])
    header = ("date\tarticles_imp\tarticles_clk\tnews_imp\tnews_clk"
              "\tpapers_imp\tpapers_clk\tother_imp\tother_clk")
    rows = {}
    if SECTIONS.exists():
        for l in SECTIONS.read_text(encoding="utf-8").splitlines()[1:]:
            if l.strip():
                rows[l.split("\t")[0]] = l
    rows[today] = line
    SECTIONS.write_text("\n".join([header] + [rows[k] for k in sorted(rows)])
                        + "\n", encoding="utf-8")

    # 施策前の基準値と比べる。2026-08-15 の noindex 適用時点の28日実績。
    base_art, base_news = 351.0, 1321.0
    art, news = agg["articles"][0], agg["news"][0]
    return (f"自社記事 {art:.0f}（施策前 {base_art:.0f}） / "
            f"ニュース {news:.0f}（施策前 {base_news:.0f}）")


def corner_performance(pages: list) -> list[dict]:
    """コーナー（棚）ごとに、投じた本数と得た反応を並べる。

    実測（2026-08-15）で分かったのは、**本数の多い棚ほど成果が出ていない**
    ということだった。AI解体新書は131本で全体の55%を占めるのに沈黙が大半、
    一方で中の鬼は23本でクリック率20%（サイト平均3.1%の6倍）。
    どこに書く時間を使うかを、感触ではなく1本あたりの反応で決めるための表。
    """
    tag_of: dict[str, str] = {}
    for md in ARTICLES.glob("*.ja.md"):
        m = re.search(r"^tag:\s*(.+)$", md.read_text(encoding="utf-8"), re.M)
        tag_of[md.name[: -len(".ja.md")]] = m.group(1).strip() if m else "?"

    # コーナーの一覧ページ（/naka/ など）は記事ではないが、棚の実力の一部。
    # 個別記事とは分けて数える。混ぜると「中の鬼はCTR20%」のように、
    # 実際には一覧ページ1枚が稼いだ数字を棚全体の実力と読み違える。
    sys.path.insert(0, str(ROOT))
    try:
        from aioni import config
        index_of = {c["tag"]: f"/{c['id']}/" for c in config.ARTICLE_CATEGORIES}
    except Exception:  # noqa: BLE001
        index_of = {}
    tag_by_index = {v: k for k, v in index_of.items()}

    agg: dict[str, dict] = {}
    for tag in set(tag_of.values()) | set(index_of):
        agg[tag] = {"tag": tag, "articles": 0, "imp": 0, "clicks": 0,
                    "idx_imp": 0, "idx_clicks": 0}
    for slug, tag in tag_of.items():
        agg[tag]["articles"] += 1
    for r in pages:
        path = short(r["keys"][0])
        if path in tag_by_index:
            a = agg[tag_by_index[path]]
            a["idx_imp"] += r["impressions"]
            a["idx_clicks"] += r["clicks"]
            continue
        tag = tag_of.get(path.strip("/").replace("articles/", ""))
        if not tag:
            continue
        agg[tag]["imp"] += r["impressions"]
        agg[tag]["clicks"] += r["clicks"]
    out = [a for a in agg.values() if a["articles"]]
    for a in out:
        a["ctr"] = (a["clicks"] / a["imp"] * 100) if a["imp"] else 0.0
        a["per"] = a["clicks"] / a["articles"] if a["articles"] else 0.0
        a["idx_ctr"] = (a["idx_clicks"] / a["idx_imp"] * 100) if a["idx_imp"] else 0.0
    out.sort(key=lambda z: -z["per"])
    return out


def append_history(daily: list) -> list[str]:
    """日別実測を履歴に積む。既にある日付は上書きしない（確定値優先）。"""
    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if HISTORY.exists():
        for line in HISTORY.read_text(encoding="utf-8").splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) >= 4:
                existing[parts[0]] = line
    for r in daily:
        d = r["keys"][0]
        existing[d] = (f"{d}\t{int(r['impressions'])}\t{int(r['clicks'])}"
                       f"\t{r['position']:.1f}")
    lines = ["date\timpressions\tclicks\tposition"]
    lines += [existing[k] for k in sorted(existing)]
    HISTORY.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines[1:]


def week_compare(hist: list[str]) -> str:
    """直近7日と、その前7日を比べる。増えているのか減っているのか。"""
    rows = [l.split("\t") for l in hist]
    if len(rows) < 14:
        return "（比較には14日分の履歴が要ります。いまは%d日分）" % len(rows)
    cur, prev = rows[-7:], rows[-14:-7]
    ci, cc = sum(int(r[1]) for r in cur), sum(int(r[2]) for r in cur)
    pi, pc = sum(int(r[1]) for r in prev), sum(int(r[2]) for r in prev)

    def pct(a, b):
        return "±0%" if b == 0 else f"{(a - b) / b * 100:+.0f}%"
    return (f"表示 {pi} → {ci}（{pct(ci, pi)}） / "
            f"クリック {pc} → {cc}（{pct(cc, pc)}）")


def main() -> int:
    days = 28
    for a in sys.argv[1:]:
        if a.startswith("--days="):
            days = int(a.split("=", 1)[1])

    try:
        pq, daily, pages, start, end = fetch(days)
    except Exception as e:  # noqa: BLE001 — 日次を止めない
        print("   ⚠️ Search Console を読めませんでした:", e)
        print("      認証が要ります（実行機で一度だけ）:")
        print("      gcloud auth application-default login \\")
        print("        --scopes=https://www.googleapis.com/auth/webmasters.readonly,"
              "https://www.googleapis.com/auth/cloud-platform")
        return 1

    hist = append_history(daily)
    # 既に noindex にしたページの実績は、提案の対象から外す（対処済み）。
    # 集計や推移からは外さない。数字は事実として残す。
    done = noindexed()
    live = [r for r in pq if short(r["keys"][0]) not in done]

    cannibals = find_cannibals(live)
    first, second = find_near_miss(live)
    silent = find_silent(pages)
    commercial = find_commercial(pq)   # ここは対処済みも含めて需要として見る
    corners = corner_performance(pages)
    sections = append_sections(pages)
    save_queries(pq, commercial)       # 測った結果を翌日の記事づくりへ渡す
    tot_i = sum(r["impressions"] for r in daily)
    tot_c = sum(r["clicks"] for r in daily)

    L: list[str] = []
    L.append(f"# AIの鬼 実測レビュー — {datetime.date.today()}")
    L.append("")
    L.append(f"対象期間 {start} 〜 {end}（Search Console は2〜3日遅れて確定）")
    L.append("")
    L.append("## 推移")
    L.append("")
    L.append(f"- {days}日合計: 表示 {tot_i:.0f} / クリック {tot_c:.0f}")
    L.append(f"- 週比較: {week_compare(hist)}")
    L.append(f"- 表示のあったURL: {len(pages)}")
    L.append("")
    L.append("### 2026-08-15 の賭けの答え合わせ")
    L.append("")
    L.append(f"- {sections}")
    L.append("")
    L.append("ニュース個別1,187ページを noindex にした日。共食いの解消を狙ったが、")
    L.append("後で数え直すと共食いは171クエリ中4件、実害は1件だけで根拠は薄かった。")
    L.append("捨てた表示は確実（66%）、得るもの（自社記事の繰り上がり）は仮説。")
    L.append("**自社記事の表示が施策前を上回れば成功、横ばい以下なら表示を捨てただけ。**")
    L.append("判定は2026-09-12前後（noindexが効くまで数週間かかるため）。")
    L.append("")

    L.append("## 0. どの棚に書くべきか（1本あたりの反応）")
    L.append("")
    L.append("記事だけの数字と、コーナー一覧ページ1枚の数字を分けています。")
    L.append("混ぜると、一覧1枚が稼いだ数字を棚全体の実力と読み違えます。")
    L.append("")
    L.append("| コーナー | 本数 | 記事の表示 | 記事のクリック | 記事CTR "
             "| 1本あたり | 一覧ページ |")
    L.append("|---|---:|---:|---:|---:|---:|---|")
    for a in corners:
        idx = (f"{a['idx_imp']:.0f}表示 {a['idx_clicks']:.0f}クリック "
               f"({a['idx_ctr']:.0f}%)" if a["idx_imp"] else "—")
        L.append(f"| {a['tag']} | {a['articles']} | {a['imp']:.0f} | "
                 f"{a['clicks']:.0f} | {a['ctr']:.1f}% | {a['per']:.2f} | {idx} |")
    L.append("")
    if corners:
        best, worst = corners[0], corners[-1]
        L.append(f"いま一番効いているのは **{best['tag']}**"
                 f"（{best['articles']}本で1本あたり{best['per']:.2f}クリック）、"
                 f"一番効いていないのは **{worst['tag']}**"
                 f"（{worst['articles']}本で{worst['per']:.2f}）。")
        L.append("本数の多い棚が効いているとは限りません。"
                 "書く時間をどこに使うかは、この列で決めてください。")
    L.append("")

    L.append("## 1. 共食い（同じ検索語で自社ページ同士が競合）")
    L.append("")
    if not cannibals:
        L.append("なし。")
    else:
        L.append("先頭に立っているページがクリックを取れていない組だけを挙げます。")
        L.append("")
        for c in cannibals[:10]:
            L.append(f"- **{c['query']}** … `{c['top']}` が{c['top_pos']:.1f}位で"
                     f"{c['top_imp']:.0f}表示・クリック0")
            for u, p in c["rivals"][:3]:
                L.append(f"    - 後ろに `{u}`（{p:.1f}位）")
    L.append("")

    L.append("## 2. 惜しい（1ページ目なのにクリック0＝タイトルの問題）")
    L.append("")
    if not first:
        L.append("なし。")
    else:
        for r in first[:15]:
            L.append(f"- {r['impressions']:.0f}表示 {r['position']:.1f}位 "
                     f"「{r['keys'][1]}」→ `{short(r['keys'][0])}`")
    L.append("")

    L.append("## 3. あと一歩（11〜20位。加筆と内部リンクで1ページ目が狙える）")
    L.append("")
    if not second:
        L.append("なし。")
    else:
        for r in second[:15]:
            L.append(f"- {r['impressions']:.0f}表示 {r['position']:.1f}位 "
                     f"「{r['keys'][1]}」→ `{short(r['keys'][0])}`")
    L.append("")

    L.append(f"## 4. 沈黙（公開{SILENT_AFTER_DAYS}日以上・表示ほぼ0の自社記事）")
    L.append("")
    if not silent:
        L.append("なし。")
    else:
        L.append(f"{len(silent)}本。増やす前に、この山を統合するか書き直す方が効きます。")
        L.append("")
        for slug, age, title in silent[:20]:
            L.append(f"- `{slug}`（公開{age}日）{title}")
        if len(silent) > 20:
            L.append(f"- …ほか{len(silent) - 20}本")
    L.append("")

    L.append("## 5. 仕事につながる検索語（ここが本丸）")
    L.append("")
    if not commercial:
        L.append("この期間は拾えていません。")
    else:
        L.append("研修・見積・導入・選定など、相談につながる語です。")
        L.append("順位が低くても表示が出ている＝需要は実在し、Google は当社を")
        L.append("候補として認識しています。**書けば取れる余地がある需要**なので、")
        L.append("表示回数の大小で切らずに見てください。")
        L.append("")
        for a in commercial[:20]:
            pages_s = " / ".join(f"`{p}`" for p in a["pages"])
            L.append(f"- **{a['query']}** … {a['imp']:.0f}表示 "
                     f"クリック{a['clicks']:.0f} 最高{a['best']:.0f}位 → {pages_s}")
        L.append("")
        L.append("> ここは自動生成では取れません。一般論の記事は大手に勝てないためです。")
        L.append("> 勝てるのは当社が実際にやった記録（出した見積の内訳、"
                 "自社研修の結果、導入して失敗した件）だけです。")
    L.append("")

    L.append("## 次にやる1件")
    L.append("")
    if cannibals:
        c = cannibals[0]
        L.append(f"**共食いの解消**: 「{c['query']}」で `{c['top']}` を noindex にするか、"
                 f"本命ページへ canonical を向ける。表示{c['top_imp']:.0f}回分が"
                 f"クリックにならないまま捨てられています。")
    elif first:
        r = first[0]
        L.append(f"**タイトルの書き換え**: `{short(r['keys'][0])}` は"
                 f"「{r['keys'][1]}」で{r['position']:.1f}位・{r['impressions']:.0f}表示・"
                 f"クリック0。順位は足りているので、検索結果の見出しで負けています。")
    elif second:
        r = second[0]
        L.append(f"**加筆**: `{short(r['keys'][0])}` は「{r['keys'][1]}」で"
                 f"{r['position']:.1f}位。1ページ目まであと少しです。")
    else:
        L.append("実測上の明確な機会はありません。新規記事の投入に回してください。")
    L.append("")
    L.append("---")
    L.append("")
    L.append("施策は1日1系統だけ打つこと。同じ日に複数変えると、"
             "順位が動いた理由を後から追えなくなります。")
    L.append("")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{datetime.date.today()}.md"
    out.write_text("\n".join(L), encoding="utf-8")

    print(f"   {days}日: 表示{tot_i:.0f} クリック{tot_c:.0f} / {week_compare(hist)}")
    print(f"   共食い{len(cannibals)}組 惜しい{len(first)}件 "
          f"あと一歩{len(second)}件 沈黙{len(silent)}本")
    if cannibals:
        c = cannibals[0]
        print(f"   → 次の1件: 「{c['query']}」で {c['top']} が"
              f"{c['top_pos']:.1f}位・クリック0")
    print(f"   レポート: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

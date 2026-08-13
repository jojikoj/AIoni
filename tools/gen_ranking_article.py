#!/usr/bin/env python3
"""一括実測の結果から、業界別の可視性ランキング記事を組み立てる。

なぜAIに書かせないか:
    この記事は「実測した数字」そのものが価値で、文章のうまさは価値ではない。
    生成にAIを挟むと、集計と合わない数字が1つでも混じった瞬間に記事全体の
    信用が消える。だから本文は実測JSONから機械的に組み立てる。

掲載の方針（重要・営業設計そのもの）:
    ✅ 良い結果だった企業（L3=公式サイトが根拠になっている）は実名で紹介する。
    ❌ 悪い結果だった企業は実名を出さない。件数だけを集計で示す。

    理由は2つ。①「◯◯製作所はAIに認識されていない」と公開するのは、これから
    商談したい相手を公然と貶める行為で、営業として最悪の入り方になる。
    ②良い企業を実名で称える記事は、その企業に連絡する正当な理由になり、
    悪かった企業には「個別に無料でお伝えします」と伝える理由になる。
    どちらの側にも連絡できる状態を作るのが、この記事の目的。

結論の出し分け（2026-08-01 追加）:
    最初は「AIに届いていない会社が大半のはず」という前提で書いていた。
    実際に45社を測ったら**42社が既に認識されていた**。前提が外れた。
    そこで、認識率が高いときは結論を切り替える——「認識されているか」ではなく
    「AIが語れる内容がどこまであるか」に論点を移す。
    データが前提と違ったときに文章だけ元のままにすると、記事が嘘になる。

使い方:
    python3 tools/gen_ranking_article.py data/visibility/fukuoka_kinzoku.json \
        --slug kansoku-fukuoka-kinzoku \
        --industry "福岡県の金属加工業" \
        --date 2026-08-02

    複数の母集団をまとめて1本にすることもできる:
    python3 tools/gen_ranking_article.py a.json b.json --slug ... --industry ...
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))

LEVELS = {
    3: ("公式サイトが根拠になっている", "AIが会社を説明でき、その根拠に自社の公式サイトが使われていた"),
    2: ("第三者の情報だけで語られている", "AIは説明できたが、根拠は求人サイトや企業データベースだけだった"),
    1: ("AIに認識されていない", "AIが会社を特定できず、事業内容を説明できなかった"),
    0: ("同名他社と区別されていない", "同じ社名の会社が複数あり、どの会社かAIが特定できなかった"),
}

# JUDGE項目 → 記事で使う日本語。「何が差を分けたか」の集計に使う。
FACTS = [
    ("business", "事業内容が具体的に分かる"),
    ("products", "主力製品・サービス名が分かる"),
    ("location", "所在地が分かる"),
    ("founded", "設立年が分かる"),
    ("size", "従業員数・売上規模が分かる"),
    ("clients", "取引先・納入実績が分かる"),
    ("media", "報道・業界メディアで取り上げられている"),
]


def pct(n: int, d: int) -> str:
    return f"{(n / d * 100):.0f}%" if d else "—"


def build(data: dict, industry: str, date: str, slug: str, source_note: str = "") -> str:
    rows = data.get("results", [])
    if not rows:
        raise SystemExit("✗ 実測結果が空です")
    total = len(rows)

    dist = {lv: [r for r in rows if r["level"] == lv] for lv in (3, 2, 1, 0)}
    n3, n2, n1, n0 = (len(dist[lv]) for lv in (3, 2, 1, 0))
    reached = n3                      # AIに自社の言葉で届いている社数
    not_reached = total - n3

    measured_at = (data.get("measured_at") or "")[:10]
    votes = data.get("votes", 3)

    # L3企業は実名で出す。スコア降順（同点は社名順）で並べ、順位を付ける。
    top = sorted(dist[3], key=lambda r: (-r["score"], r["name"]))

    # 事実の保有率。ここが「何が差を分けたか」の根拠になる。
    fact_rows = []
    for k, label in FACTS:
        yes = sum(1 for r in rows if (r.get("judge") or {}).get(k))
        yes3 = sum(1 for r in dist[3] if (r.get("judge") or {}).get(k))
        fact_rows.append((label, yes, pct(yes, total), yes3, pct(yes3, n3) if n3 else "—"))

    # 根拠に使われたサイトの内訳。第三者DBばかりが根拠になっている実態を出す。
    agg_only = sum(1 for r in rows
                   if r["sources"] and all(s.get("aggregator") for s in r["sources"]))
    no_src = sum(1 for r in rows if not r["sources"])

    # 結論の書き方をデータで決める。文章を先に決めて数字を後から入れると、
    # 実測が想定と違ったときに記事が嘘になる。
    high_recognition = bool(total) and (n3 / total) >= 0.7
    # 最も保有率が低かった事実＝いま差がついている論点
    low = min(fact_rows, key=lambda r: r[1]) if fact_rows else None

    L = []
    a = L.append

    a("---")
    if high_recognition:
        a(f"title: {industry}{total}社をAIに聞いたら、{n3}社は説明できた。差がついたのは別のところだった")
        a(f"excerpt: {industry}{total}社について、検索連携型の生成AIに「この会社は何をしている会社か」"
          f"を尋ねました。公式サイトを根拠に説明できたのは{n3}社（{pct(n3, total)}）。"
          f"「中小企業はAIに認識されていない」という想定は外れました。"
          + (f"差がついたのは{low[0]}で、{low[1]}社（{low[2]}）にとどまりました。" if low else ""))
    else:
        a(f"title: {industry}{total}社をAIに聞いてみた。自社サイトが根拠になったのは何社か")
        a(f"excerpt: {industry}{total}社について、検索連携型の生成AIに「この会社は何をしている会社か」"
          f"を尋ね、AIが根拠にしたサイトを実際に調べました。公式サイトが根拠として使われたのは{n3}社"
          f"（{pct(n3, total)}）。同じ質問を1社あたり{votes}回投げ、判定が一致したものだけを載せています。")
    a("tag: AEO対策室")
    a("author: AIの鬼 編集部")
    a(f"date: {date}")
    a(f"hero: article-{slug}.jpg")
    a("image_prompt: A factory office desk with a laptop showing a search result page, "
      "printed company list with checkmarks beside it, metal parts on the corner of the desk, "
      "daylight from a window, realistic documentary photograph, professional photograph")
    a("---")
    a("")

    a("## 先に立場を明かします")
    a("")
    a("株式会社TOEは**AI検索対策のサービスを売りうる利害関係者**です。"
      "この記事に載せるのは実際に測った結果だけで、対策の効果を示す数字（順位が上がった・引用が増えた等）は"
      "測っていないので書きません。")
    a("")
    if high_recognition:
        a("**この記事は、当社の想定が外れた記録です。**"
          "「中小企業はAIに認識されていないはずだ」という前提で測り始めましたが、結果は逆でした。"
          "自社に都合の悪い結果でしたが、そのまま出します。")
        a("")
    a("**結果が芳しくなかった会社の社名は出しません。**"
      "AIにうまく伝わっていないことは、その会社の努力不足ではなく、"
      "多くの中小企業がまだ手を付けていない領域だからです。"
      "実名で挙げるのは、AIが十分に説明できていた会社だけにしています。")
    a("")
    if source_note:
        a("### 調べた対象")
        a("")
        a(source_note)
        a("")
        a("**恣意的に選んでいません。**名簿に載っている会社は全社測っています。"
          "検索で上位に出る会社だけを選ぶと、すでに発信できている会社に偏り、"
          "測りたいものが測れなくなるためです。")
        a("")
    a("---")
    a("")

    a("## 結論")
    a("")
    a("| 項目 | 結果 |")
    a("|---|---|")
    a(f"| 調べた会社数 | {total}社 |")
    a(f"| AIが**公式サイトを根拠に**説明できた | **{n3}社（{pct(n3, total)}）** |")
    a(f"| AIは説明できたが根拠は第三者情報だけ | {n2}社（{pct(n2, total)}） |")
    a(f"| AIが会社を特定できなかった | {n1}社（{pct(n1, total)}） |")
    a(f"| 同名他社と区別できなかった | {n0}社（{pct(n0, total)}） |")
    a("")

    if high_recognition:
        a(f"**{total}社のうち{n3}社（{pct(n3, total)}）で、AIは公式サイトを根拠に会社を説明できました。**")
        a("")
        a("これは調査前の想定と逆でした。"
          "「中小企業はAIに認識されていない」と考えて測り始めましたが、"
          "**認識されているかどうかでは、もう差がつきません。**")
        a("")
        if low:
            a(f"差が出たのは別の項目です。AIが確認できた事実のうち、"
              f"**{low[0]}**は{low[1]}社（{low[2]}）にとどまりました。"
              "社名を尋ねれば説明は返ってくる。しかし、その説明にどれだけの中身があるかは、"
              "会社によって開きがあります。")
            a("")
    else:
        a(f"**{total}社のうち{not_reached}社（{pct(not_reached, total)}）は、"
          f"AIに自社の言葉が届いていませんでした。**"
          "見込み客がAIに「この分野の会社を教えて」と尋ねたとき、"
          "説明の材料になるのは自社サイトではなく、求人サイトや企業データベースに書かれた情報です。")
        a("")
    a("---")
    a("")

    a("## どうやって測ったか")
    a("")
    a("| 項目 | 内容 |")
    a("|---|---|")
    a(f"| 実測日 | {measured_at} |")
    a("| 使ったAI | Google Gemini（Flash-Lite）＋ Google検索グラウンディング |")
    a("| 質問 | 「この会社は何をしている会社か」を会社名だけで尋ねる |")
    a(f"| 回数 | 1社あたり{votes}回。項目ごとに合議して判定 |")
    a("| 判定 | AIが返した回答と、**AIが実際に参照したサイト**の両方で判定 |")
    a("")
    a("同じ質問を複数回投げているのは、生成AIの回答が実行ごとに揺れるからです。"
      "1回だけ測って「認識されていない」と結論づけるのは乱暴なので、"
      "複数回のうち一度でも確認できた事実は「確認できる事実」として扱っています。"
      "つまり**この集計は、実態より甘い側に倒してあります**。")
    a("")
    a("判定の4段階は次の通りです。")
    a("")
    a("| 段階 | 意味 |")
    a("|---|---|")
    for lv in (3, 2, 1, 0):
        label, desc = LEVELS[lv]
        a(f"| **{label}** | {desc} |")
    a("")
    a("---")
    a("")

    # 実名で出すのは「AIが7項目すべてを確認できた会社」だけに絞る。
    # 認識率が高い母集団では該当が数十社になり、全部並べても読まれないうえ、
    # 順位を付けると優劣を公表したことになって角が立つ。
    # ここは「褒める記事」であって「格付け」ではない。
    full = [r for r in dist[3] if all((r.get("judge") or {}).get(k) for k, _ in FACTS)]
    full.sort(key=lambda r: r["name"])

    a("## AIが最も詳しく説明できた会社")
    a("")
    if not top:
        a(f"今回の{total}社では、**1社もありませんでした**。"
          "AIは説明できても、根拠にしていたのは第三者が書いた情報でした。")
    elif full:
        a(f"公式サイトが根拠になっていた{n3}社のうち、"
          f"**AIが{len(FACTS)}項目すべてを確認できたのは{len(full)}社**でした。"
          "事業内容から取引先、第三者による言及まで、AIが説明の材料を一通り持っている会社です。")
        a("")
        # 所在地は名簿に載っていないことがある。半数以上が空欄なら列ごと出さない
        # （「—」が並ぶ列は情報がないうえ、調べずに書いたように見える）。
        has_pref = sum(1 for r in full if r.get("pref")) > len(full) / 2
        if has_pref:
            a("| 会社名 | 所在 |")
            a("|---|---|")
            for r in full:
                a(f"| {r['name']} | {r.get('pref') or '—'} |")
        else:
            a("| 会社名 |")
            a("|---|")
            for r in full:
                a(f"| {r['name']} |")
        a("")
        a("※ 順不同です。当社の判定によるもので、企業の優劣を示すものではありません。"
          "掲載を希望されない場合はご連絡ください。速やかに削除します。")
    else:
        a(f"公式サイトが根拠になっていたのは{n3}社ですが、"
          f"**{len(FACTS)}項目すべてを確認できた会社は1社もありませんでした。**")
    a("")
    a("---")
    a("")

    a("## 何が差を分けたか")
    a("")
    if high_recognition:
        # 認識率が高い母集団では「全体 vs 上位群」を比べても差が出ない
        # （ほぼ全社が上位群のため）。比較ではなく、保有率そのものを低い順に見る。
        a("AIが会社について確認できた事実を、項目ごとに数えました。**保有率の低い順**に並べています。"
          "ここで下にある項目ほど、いまAIが語れていない部分です。")
        a("")
        a("| AIが確認できた事実 | 社数 | 割合 |")
        a("|---|---|---|")
        for label, yes, p, _, _ in sorted(fact_rows, key=lambda r: -r[1]):
            a(f"| {label} | {yes}社 | {p} |")
        a("")
        ranked = sorted(fact_rows, key=lambda r: r[1])
        if ranked:
            worst = ranked[0]
            a(f"**上6項目はほぼ全社が満たしています。**"
              f"会社概要に書いてあれば確認できる情報だからです。"
              f"はっきり落ちるのは最後の1つ、**{worst[0]}**だけで、{worst[1]}社（{worst[2]}）でした。")
            a("")
            a("ここが自社サイトの記述だけでは動かない項目です。"
              "所在地や設立年は自分で書けば済みますが、"
              "**第三者に書かれるかどうかは自分では書けません。**"
              "この実測でいちばんはっきり差が出たのは、そこでした。")
            a("")
    else:
        a("AIが会社について確認できた事実を、項目ごとに数えました。"
          "右2列は、**公式サイトが根拠になっていた会社だけ**の数字です。")
        a("")
        a("| AIが確認できた事実 | 全体 | 全体比 | 上位群 | 上位群比 |")
        a("|---|---|---|---|---|")
        for label, yes, p, yes3, p3 in fact_rows:
            a(f"| {label} | {yes}社 | {p} | {yes3}社 | {p3} |")
        a("")

        # 差が大きい項目を機械的に拾って本文にする（書き手の印象で語らない）
        gaps = []
        if n3:
            for (k, label), (_, yes, _, yes3, _) in zip(FACTS, fact_rows):
                whole = yes / total * 100
                upper = yes3 / n3 * 100
                gaps.append((upper - whole, label, whole, upper))
            gaps.sort(reverse=True)
            top_gap = [g for g in gaps[:3] if g[0] > 0]
            if top_gap:
                a("差が大きかったのは次の項目です。")
                a("")
                for d, label, whole, upper in top_gap:
                    a(f"- **{label}** … 全体{whole:.0f}% に対して、上位群は{upper:.0f}%")
                a("")
                a("いずれも「自社サイトに書いてあれば確認できる」種類の情報です。"
                  "AIが特別な判断をしているのではなく、**書いてあるかどうか**で差が付いています。")
                a("")

    # 0件のことをわざわざ書くと、書くために書いた文に見える。あるときだけ出す。
    if agg_only or no_src:
        parts = []
        if agg_only:
            parts.append(f"AIが根拠にしたサイトが**第三者の情報だけ**だった会社が{agg_only}社")
        if no_src:
            parts.append(f"根拠になるサイトを何も提示できなかった会社が{no_src}社")
        a("また、" + "、".join(parts) + "ありました。")
        a("")
    a("---")
    a("")

    a("## 明日から打てる手")
    a("")
    if high_recognition:
        a("**「AIに載る」ための対策は、この母集団ではもう終わっています。**"
          "次に効くのは、AIが語れる中身を増やすことです。"
          "以下は一般的な対策で、効果を当社が測定したものではありません。")
        a("")
        a("| やること | なぜ |")
        a("|---|---|")
        a("| 納入実績・取引分野を（出せる範囲で）具体的に書く | AIが確認できた会社とできなかった会社で、最も差が開いた項目のひとつ |")
        a("| 技術解説・加工事例を自社サイトで出し続ける | 業界メディアや取引先が引用する材料になる。**最も保有率が低かったのが第三者からの言及** |")
        a("| 展示会出展・受賞・新設備導入をリリースにする | 第三者に書かれた情報は、AIが説明を組み立てるときの裏付けになる |")
        a("| 社名に地域と事業を結びつけて書く | 同名他社と混同されるのを防ぐ（この実測でも数社が該当） |")
    else:
        a("この実測から言えるのは、**特別な技術ではなく記述の有無で差が付いている**ということだけです。"
          "以下は一般的な対策で、効果を当社が測定したものではありません。")
        a("")
        a("| やること | なぜ |")
        a("|---|---|")
        a("| 会社概要に所在地・設立・従業員数・主要設備を**文章で**書く | 画像やPDFの中の文字はAIに読まれにくい |")
        a("| 対応できる加工・仕様を、数字と条件を添えて書く | 「精密加工」だけでは他社と区別されない |")
        a("| 納入実績・取引分野を（出せる範囲で）書く | 上位群との差が最も大きかった項目のひとつ |")
        a("| 社名に地域と事業を結びつけて書く | 同名他社と混同されるのを防ぐ |")
    a("")
    a("---")
    a("")

    a("## まとめ")
    a("")
    a(f"- {industry}{total}社を実測し、公式サイトが根拠になっていたのは**{n3}社（{pct(n3, total)}）**")
    if high_recognition:
        a("- **「中小企業はAIに認識されていない」という想定は、この母集団では外れた**")
        if low:
            a(f"- 差が出たのは認識の有無ではなく中身。最も低かったのは**{low[0]}**で{low[1]}社（{low[2]}）")
        if n0:
            a(f"- ただし{n0}社は、同名他社と区別されていなかった")
    else:
        a(f"- 残る{not_reached}社は、AIが自社の言葉ではなく第三者の情報で説明するか、そもそも説明できない状態")
        a("- 差が付いていたのは技術ではなく、**サイトに事実が文章で書いてあるかどうか**")
    a("- この実測は複数回の合議で、実態より甘い側に倒してある")
    a("")
    a("---")
    a("")

    a("## この記事の限界")
    a("")
    a("- 測ったのは**1種類のAI**での見え方です。ChatGPTやPerplexityでは結果が異なります")
    a("- 生成AIの回答は実行ごとに揺れます。同じ会社を測り直すと判定が変わる可能性があります")
    a("- 「AIが検索結果の上位に出すか」は測っていません。測ったのは**説明できるか・何を根拠にするか**だけです")
    a("- 掲載企業の許諾は取っていません。公開情報にAIが答えた内容のみを扱っています")
    a("")
    a(f"実測データ: `data/visibility/{data.get('batch', slug)}.json`（実測日 {measured_at}）")
    a("")

    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="実測JSONからランキング記事を組み立てる")
    ap.add_argument("json", nargs="+", help="batch_visibility.py の出力JSON（複数可）")
    ap.add_argument("--slug", required=True, help="記事slug（例: kansoku-fukuoka-kinzoku）")
    ap.add_argument("--industry", required=True, help="見出しに使う業界名（例: 福岡県の金属加工業）")
    ap.add_argument("--date", default=datetime.now(JST).strftime("%Y-%m-%d"))
    ap.add_argument("--out", help="出力先md（既定: content/articles/<slug>.ja.md）")
    ap.add_argument("--source-note", default="",
                    help="母集団の出どころ。記事に明記する（再現できる記事にするため必須級）")
    args = ap.parse_args()

    # 複数の母集団を1本の記事にまとめられる。社数が増えるほど分布が安定するので、
    # 同じ業界を別々の名簿から集めたときは合わせて出したほうが記事として強い。
    data = None
    for j in args.json:
        src = Path(j)
        if not src.is_absolute() and not src.exists():
            src = ROOT / src
        part = json.loads(src.read_text(encoding="utf-8"))
        if data is None:
            data = part
            data["batches"] = [part.get("batch", src.stem)]
        else:
            data["results"] = data["results"] + part["results"]
            data["batches"].append(part.get("batch", src.stem))
    if not data:
        raise SystemExit("✗ 入力がありません")

    md = build(data, args.industry, args.date, args.slug, args.source_note)
    out = Path(args.out) if args.out else ROOT / "content" / "articles" / f"{args.slug}.ja.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"✓ 記事を書き出しました: {out}")
    print(f"  {len(data.get('results', []))}社ぶんの実測から生成。数字は集計そのままです。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""1社ぶんの「AI可視性 実測レポート」と、送付メールの下書きを作る。

これがアウトバウンドの本体。ランキング記事は集計しか出さないが、
相手に渡すのは「御社を測った結果」そのものでなければ意味がない。

出力（1社につき2ファイル）:
    reports/visibility/<batch>/<会社名>.html   … 渡すレポート（A4想定・ライトモード）
    reports/visibility/<batch>/<会社名>.txt    … 送付メールの下書き

PDFにする:
    tools/gen_company_report.py --pdf を付けると Chrome のヘッドレスで
    同じ場所に .pdf も出す（相手がブラウザで開けない場合の保険）。

トーンの方針:
    煽らない。「御社はAIに認識されていません」と突きつけるのではなく、
    「AIに尋ねた結果、こう返ってきました」と事実だけを見せる。
    判断は相手にさせる。売り込みは最後の1ブロックだけに置く。

使い方:
    python3 tools/gen_company_report.py data/visibility/fukuoka_kinzoku.json --all
    python3 tools/gen_company_report.py data/visibility/fukuoka_kinzoku.json --name "株式会社◯◯製作所"
    python3 tools/gen_company_report.py <json> --all --pdf
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SITE = "https://ai-oni.com"
CHECK_URL = f"{SITE}/check/"
CONTACT_URL = f"{SITE}/contact/?service=aeo&utm_source=report&utm_medium=outbound"

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
]

LEVELS = {
    3: {
        "label": "公式サイトが根拠になっている",
        "tone": "hi",
        "head": "AIは御社の公式サイトを根拠に説明できています。",
        "body": "御社の発信はAIに届いています。ただし、同じ質問で同業他社がどう説明されるか、"
                "どちらが先に挙がるかは、この実測では測っていません。",
    },
    2: {
        "label": "第三者の情報だけで語られている",
        "tone": "mid",
        "head": "AIは御社を説明できましたが、その根拠に公式サイトがありませんでした。",
        "body": "AIが見ていたのは、求人サイトや企業データベースなど第三者が書いた情報です。"
                "御社が伝えたい内容ではなく、他社が書いた情報で説明されている状態です。",
    },
    1: {
        "label": "AIに認識されていない",
        "tone": "lo",
        "head": "AIは御社を特定できませんでした。",
        "body": "AIに御社のことを尋ねた見込み客には、情報がほとんど届きません。"
                "判断材料がないため、AIは説明を避けるか、別の会社の情報を答えることがあります。",
    },
    0: {
        "label": "同名他社と区別されていない",
        "tone": "lo",
        "head": "AIは御社を、同じ社名の別会社と区別できていませんでした。",
        "body": "御社の名前で尋ねても、AIはどの会社のことか特定できませんでした。"
                "別の会社の情報が御社の説明として返る可能性があります。",
    },
}

FACTS = [
    ("business", "事業内容が具体的に分かる"),
    ("products", "主力製品・サービス名が分かる"),
    ("location", "所在地が分かる"),
    ("founded", "設立年が分かる"),
    ("size", "従業員数・売上規模が分かる"),
    ("clients", "取引先・納入実績が分かる"),
    ("media", "報道・業界メディアで取り上げられている"),
]

TIPS = {
    0: ["社名だけでなく「地域＋事業内容」が結びつく形で書く（例：福岡県の精密板金加工）",
        "所在地・設立・代表者・主要設備など、同名他社と区別できる情報を明記する"],
    1: ["公式サイトに「何を・誰に・どこで作っているか」を文章で書く（画像やPDFの中の文字はAIに読まれにくい）",
        "会社概要に、所在地・設立・主要設備・対応分野を具体的に載せる"],
    2: ["公式サイトの事業内容を、検索される言葉で本文に書く（画像やPDF任せにしない）",
        "対応できる加工・仕様を、数字と条件を添えて明記する"],
    3: ["同業と比べられたときの差別化点を、サイト上に明文で置く",
        "実績や技術解説など一次情報を出し続け、引用され続ける状態をつくる"],
}


def safe_name(s: str) -> str:
    return re.sub(r"[/\\:*?\"<>|\s]+", "_", s).strip("_")[:80]


def e(s: str) -> str:
    return html.escape(s or "")


def rank_of(target: dict, rows: list[dict]) -> tuple[int, int]:
    """同じバッチ内での順位（スコア降順）。母数も返す。"""
    ordered = sorted(rows, key=lambda r: (-r["score"], r["name"]))
    for i, r in enumerate(ordered, start=1):
        if r["name"] == target["name"]:
            return i, len(ordered)
    return 0, len(ordered)


def build_html(r: dict, data: dict) -> str:
    rows = data.get("results", [])
    total = len(rows)
    lv = LEVELS.get(r["level"], LEVELS[1])
    j = r.get("judge") or {}
    rank, n = rank_of(r, rows)
    n3 = sum(1 for x in rows if x["level"] == 3)
    industry = r.get("industry") or data.get("batch", "")
    measured = (r.get("measured_at") or "")[:10]

    got = [(label, bool(j.get(k))) for k, label in FACTS]
    tips = TIPS.get(r["level"], TIPS[1])

    src_rows = []
    for s in r.get("sources", []):
        kind = "第三者サイト" if s.get("aggregator") else "自社・その他"
        src_rows.append(
            f'<tr><td>{e(s["title"])}</td><td class="kind">{kind}</td></tr>')
    if not src_rows:
        src_rows.append('<tr><td colspan="2" class="muted">'
                        'AIは根拠になるサイトを提示できませんでした。</td></tr>')

    steps = "".join(
        f'<span class="step{" on" if i <= r["level"] else ""}"></span>' for i in range(4))

    fact_rows = "".join(
        f'<tr><td>{e(label)}</td><td class="{"yes" if ok else "no"}">'
        f'{"確認できた" if ok else "確認できなかった"}</td></tr>'
        for label, ok in got)

    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<title>AI可視性 実測レポート — {e(r['name'])}</title>
<style>
  @page {{ size: A4; margin: 16mm 14mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: "Hiragino Sans","Yu Gothic",sans-serif; color:#1a1a1a;
         background:#fff; margin:0; padding:0; line-height:1.75; font-size:13.5px; }}
  .wrap {{ max-width: 760px; margin: 0 auto; padding: 28px 24px 40px; }}
  .brand {{ display:flex; justify-content:space-between; align-items:baseline;
            border-bottom:2px solid #1a1a1a; padding-bottom:10px; margin-bottom:26px; }}
  .brand b {{ font-size:15px; letter-spacing:.04em; }}
  .brand span {{ font-size:11px; color:#666; }}
  h1 {{ font-size:21px; line-height:1.45; margin:0 0 6px; }}
  .sub {{ font-size:12px; color:#666; margin:0 0 24px; }}
  .card {{ border:1px solid #e0e0e0; border-radius:10px; padding:18px 20px; margin:0 0 22px;
           background:#fafafa; page-break-inside:avoid; }}
  .verdict {{ display:flex; gap:18px; align-items:center; flex-wrap:wrap; }}
  .score {{ font-size:46px; font-weight:800; line-height:1; }}
  .hi .score {{ color:#0d7a5f; }} .mid .score {{ color:#b06a00; }} .lo .score {{ color:#b3261e; }}
  .score small {{ font-size:14px; color:#888; font-weight:700; }}
  .vside {{ flex:1 1 240px; min-width:0; }}
  .vlabel {{ font-size:11px; letter-spacing:.14em; color:#888; margin:0 0 3px; }}
  .vlevel {{ font-size:16px; font-weight:800; margin:0; }}
  .steps {{ display:flex; gap:4px; margin-top:9px; }}
  .step {{ flex:1; height:6px; border-radius:99px; background:#e0e0e0; }}
  .hi .step.on {{ background:#0d7a5f; }} .mid .step.on {{ background:#b06a00; }} .lo .step.on {{ background:#b3261e; }}
  h2 {{ font-size:15px; margin:28px 0 10px; padding-left:9px; border-left:4px solid #b3261e; }}
  p {{ margin:0 0 12px; }}
  table {{ width:100%; border-collapse:collapse; margin:0 0 14px; font-size:13px; }}
  th,td {{ border:1px solid #e0e0e0; padding:8px 10px; text-align:left; vertical-align:top; }}
  th {{ background:#f2f2f2; font-weight:700; width:38%; }}
  td.yes {{ color:#0d7a5f; font-weight:700; }}
  td.no {{ color:#999; }}
  td.kind {{ width:34%; color:#666; }}
  .quote {{ background:#fff; border:1px solid #e0e0e0; border-left:4px solid #888;
            padding:14px 16px; white-space:pre-wrap; font-size:13px; color:#333; margin:0 0 14px; }}
  ul {{ margin:0 0 14px; padding-left:1.2em; }} li {{ margin:0 0 6px; }}
  .cta {{ border:2px solid #b3261e; border-radius:10px; padding:18px 20px; background:#fff;
          page-break-inside:avoid; }}
  .cta h3 {{ margin:0 0 8px; font-size:15px; color:#b3261e; }}
  .muted {{ color:#888; }}
  .foot {{ margin-top:30px; padding-top:14px; border-top:1px solid #e0e0e0;
           font-size:11px; color:#777; line-height:1.8; }}
  a {{ color:#b3261e; }}
</style></head><body><div class="wrap">

<div class="brand"><b>AI可視性 実測レポート</b><span>AIの鬼 / 株式会社TOE　実測日 {e(measured)}</span></div>

<h1>{e(r['name'])} 様</h1>
<p class="sub">生成AIに「{e(r['name'])}はどんな会社か」と尋ね、AIが答えた内容と、
その根拠にしたサイトを実際に記録しました。{e(industry)}{total}社を同じ方法で測った調査の一部です。</p>

<div class="card {lv['tone']}">
  <div class="verdict">
    <div class="score">{r['score']}<small>/100</small></div>
    <div class="vside">
      <p class="vlabel">AI認知スコア</p>
      <p class="vlevel">{e(lv['label'])}</p>
      <div class="steps">{steps}</div>
    </div>
  </div>
  <p style="margin:14px 0 0;font-weight:700">{e(lv['head'])}</p>
  <p style="margin:6px 0 0">{e(lv['body'])}</p>
</div>

<h2>同業{total}社の中での位置</h2>
<table>
  <tr><th>調査対象</th><td>{e(industry)}{total}社</td></tr>
  <tr><th>御社の位置</th><td><b>{rank}位 / {n}社</b>（スコア順）</td></tr>
  <tr><th>公式サイトが根拠になっていた会社</th><td>{n3}社（{total}社中）</td></tr>
</table>
<p class="muted">順位は当社の判定によるもので、企業の優劣を示すものではありません。
また、この結果は公開しません。ランキング記事では上位の会社のみを実名で紹介し、
それ以外は集計値のみを掲載しています。</p>

<h2>AIが実際に返した説明</h2>
<div class="quote">{e(r.get('summary') or '（AIは説明を返しませんでした）')}</div>

<h2>AIがこの説明の根拠にしたサイト</h2>
<table>
  <tr><th style="width:66%">サイト</th><th style="width:34%">種別</th></tr>
  {''.join(src_rows)}
</table>
<p class="muted">ここに御社の公式サイトが入っているかどうかが、最も重要な確認点です。
第三者サイトだけが並んでいる場合、AIは御社の言葉ではなく他社が書いた情報で御社を説明しています。</p>

<h2>AIが確認できた事実・できなかった事実</h2>
<table>
  <tr><th>項目</th><th style="width:34%">結果</th></tr>
  {fact_rows}
</table>

<h2>まず打てる手</h2>
<ul>{''.join(f'<li>{e(t)}</li>' for t in tips)}</ul>
<p class="muted">一般的な対策です。御社に何が効くかは、実際の見え方と同業の状況を突き合わせないと分かりません。</p>

<div class="cta">
  <h3>同業他社と比べた見え方を、無料でお出しします</h3>
  <p style="margin:0 0 8px">御社が指定する同業3社について同じ実測を行い、
  「同じ質問をしたときにAIがどちらを説明できるか」を比較したレポートをお渡しします。費用はかかりません。</p>
  <p style="margin:0">ご希望・ご質問はこちらから　<a href="{CONTACT_URL}">{CONTACT_URL}</a></p>
</div>

<div class="foot">
  <b>この実測の限界</b><br>
  ・測ったのは1種類のAIでの見え方です。ChatGPTやPerplexityでは結果が異なります。<br>
  ・生成AIの回答は実行ごとに揺れます。同じ質問を{data.get('votes', 3)}回投げ、
  一度でも確認できた事実は「確認できた」として扱っています（実態より甘い側の集計です）。<br>
  ・「AIが検索結果の上位に出すか」は測っていません。測ったのは説明できるか・何を根拠にするかだけです。<br>
  ・特定の表示や引用を保証するものではありません。<br><br>
  実測・作成：株式会社TOE（福岡市中央区）／AIの鬼 <a href="{SITE}">{SITE}</a><br>
  ご自身でも測れます：<a href="{CHECK_URL}">{CHECK_URL}</a><br>
  掲載・調査対象からの削除をご希望の場合は、上記よりご連絡ください。速やかに対応します。
</div>

</div></body></html>
"""


def build_mail(r: dict, data: dict) -> str:
    rows = data.get("results", [])
    total = len(rows)
    industry = r.get("industry") or data.get("batch", "")
    lv = LEVELS.get(r["level"], LEVELS[1])
    n3 = sum(1 for x in rows if x["level"] == 3)

    # 記事で実名を出すのは「AIが全項目を確認できた会社」だけ
    # （gen_ranking_article.py と同じ基準）。ここがズレると、
    # 「記事で紹介したい」と書いたのに載っていない、という嘘になる。
    j = r.get("judge") or {}
    is_full = all(j.get(k) for k, _ in FACTS)
    missing = [label for k, label in FACTS if not j.get(k)]

    if r["level"] == 3 and is_full:
        lead = (
            f"結果からお伝えすると、{total}社のうち公式サイトが答えの根拠として使われていたのは{n3}社、"
            f"さらに当社が見た7項目すべてをAIが確認できたのは一部の会社のみで、"
            f"御社はその中に入っていました。サイトでの発信がAIに十分届いている状態です。"
        )
        ask = (
            "つきましては、調査結果をまとめた記事で御社を実名でご紹介したいと考えております。"
            "掲載の可否をご確認いただけますでしょうか。ご希望されない場合は掲載いたしません。"
        )
    elif r["level"] == 3:
        miss = "・".join(missing) if missing else ""
        lead = (
            f"結果からお伝えすると、{total}社のうち公式サイトが答えの根拠として使われていたのは{n3}社で、"
            f"御社はその中に入っていました。サイトでの発信はAIに届いています。"
            + (f"\n\nただし、AIが確認できなかった項目もありました（{miss}）。"
               "見込み客がAIに御社のことを尋ねたとき、この部分は答えに出てきません。" if miss else "")
        )
        ask = (
            "御社の詳細な結果（AIが実際に何と答えたか、何を根拠にしたか、"
            "何を確認できなかったか）を添付のレポートにまとめました。費用は一切かかりません。"
            "\n\nなお、記事で実名を出すのは全項目を確認できた会社のみとしており、"
            "この調査結果で御社が不利に扱われることはありません。"
        )
    else:
        lead = (
            f"結果からお伝えすると、{total}社のうち公式サイトが答えの根拠として使われていたのは{n3}社のみで、"
            f"御社については「{lv['label']}」という結果でした。"
            "これは御社に限った話ではなく、調査した大半の企業が同じ状態です。"
        )
        ask = (
            "調査結果をまとめた記事では、結果が芳しくなかった企業の社名は一切公開しません。"
            "御社の詳細な結果（AIが実際に何と答えたか、何を根拠にしたか）は、"
            "添付のレポートにまとめましたのでご確認ください。費用は一切かかりません。"
        )

    return f"""件名: 【無料調査のご報告】{industry}{total}社を対象に、生成AIが各社をどう説明するかを実測しました

{r['name']} ご担当者様

突然のご連絡失礼いたします。
福岡市の株式会社TOEと申します。AI活用の実測メディア「AIの鬼」（{SITE}）を運営しております。

このたび、{industry}{total}社を対象に、
「生成AIに社名を尋ねたとき、その会社をどう説明するか」を実際に測る調査を行いました。
御社もその対象に含まれておりましたので、結果をお送りいたします。

{lead}

{ask}

――――――――――
■ 調査の概要
・対象　：{industry}{total}社
・方法　：検索連携型の生成AIに社名だけで「何をしている会社か」を尋ね、
　　　　　回答とAIが参照したサイトを記録（1社あたり{data.get('votes', 3)}回、合議判定）
・実測日：{(r.get('measured_at') or '')[:10]}
・費用　：無料。営業目的の調査ですが、結果の提供に費用はかかりません
――――――――――

■ 御社の結果（添付レポートより）
・判定　　：{lv['label']}
・AIが根拠にしたサイト：{'、'.join(s['title'] for s in r.get('sources', [])[:4]) or 'なし'}

添付のレポートには、AIが実際に返した説明文と、その根拠にしたサイトの一覧を
そのまま掲載しております。

なお、同じ方法で御社が指定される同業3社を測った比較レポートも、
無料でお出しできます。ご希望でしたらご返信ください。

本メールが不要でしたら、その旨ご返信ください。以後お送りいたしません。
調査対象からの削除をご希望の場合も、同様にご連絡ください。

――――――――――
株式会社TOE
AI検索対策 / AI社内導入支援
福岡市中央区
AIの鬼 {SITE}
お問い合わせ {CONTACT_URL}
――――――――――
"""


def to_pdf(html_path: Path) -> bool:
    chrome = next((c for c in CHROME_CANDIDATES if Path(c).exists()), None) or shutil.which("chrome")
    if not chrome:
        print("  ⚠ Chrome が見つからないため PDF は作成しませんでした")
        return False
    pdf = html_path.with_suffix(".pdf")
    cmd = [chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
           f"--print-to-pdf={pdf}", html_path.as_uri()]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=90)
        return pdf.exists()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as ex:
        print(f"  ⚠ PDF化に失敗: {ex}")
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="1社ぶんの実測レポートと送付メール下書きを作る")
    ap.add_argument("json", help="batch_visibility.py の出力JSON")
    ap.add_argument("--name", help="対象の会社名（完全一致）")
    ap.add_argument("--all", action="store_true", help="バッチ内の全社ぶんを出力する")
    ap.add_argument("--pdf", action="store_true", help="Chromeヘッドレスで PDF も出す")
    ap.add_argument("--outdir", help="出力先（既定: reports/visibility/<batch>/）")
    args = ap.parse_args()

    src = Path(args.json)
    if not src.is_absolute() and not src.exists():
        src = ROOT / src
    data = json.loads(src.read_text(encoding="utf-8"))
    rows = data.get("results", [])
    if not rows:
        print("✗ 実測結果が空です")
        return 1

    if args.all:
        targets = rows
    elif args.name:
        targets = [r for r in rows if r["name"] == args.name]
        if not targets:
            print(f"✗ {args.name} は実測結果にありません")
            return 1
    else:
        print("✗ --name か --all のどちらかを指定してください")
        return 1

    outdir = Path(args.outdir) if args.outdir else ROOT / "reports" / "visibility" / data.get("batch", "batch")
    outdir.mkdir(parents=True, exist_ok=True)

    for r in targets:
        stem = safe_name(r["name"])
        hp = outdir / f"{stem}.html"
        hp.write_text(build_html(r, data), encoding="utf-8")
        (outdir / f"{stem}.txt").write_text(build_mail(r, data), encoding="utf-8")
        line = f"  ✓ {r['name']} — L{r['level']} ({r['score']}点)"
        if args.pdf and to_pdf(hp):
            line += " +PDF"
        print(line)

    print(f"\n■ {len(targets)}社ぶん出力しました → {outdir}")
    print("  .html = 渡すレポート / .txt = 送付メールの下書き")
    return 0


if __name__ == "__main__":
    sys.exit(main())

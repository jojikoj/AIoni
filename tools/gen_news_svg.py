"""画像のない集約ニュース用に、トピック別の図解SVGを生成する。

なぜ写真ではなくSVGか:
  収集した600件のうち画像を持つのは85件（14%）だけ。残り515件に
  Fluxのイメージ写真24枚を割り当てると、同じ写真が1枚あたり20回以上出る。
  「中身のない量産サイト」に見えるうえ、生成に費用もかかる。
  SVGなら費用ゼロで何百通りでも作れ、サイトの配色にそのまま合う。

  ※オリジナル記事（content/articles/）のヒーローは Flux 写真のまま。
    こちらは集約ニュース（ItemList）専用。混ぜないこと。

方針:
  - 文字を入れない（一覧に並ぶので言語に依存させない）
  - トピックごとに意匠を変える。何の話かが色と形で伝わればよい
  - 装飾のためのAIっぽい発光やグラデーションは使わない
  - サイトのCSS変数と同じ色だけを使う

実行:
    python3 tools/gen_news_svg.py          # 未生成のものだけ作る
    python3 tools/gen_news_svg.py --force  # 全部作り直す
"""
from __future__ import annotations

import hashlib
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "img"

W, H = 1024, 576

# style.css の変数と同じ値。ここを勝手に増やさない
BG = "#fbfcfe"
LINE = "#e3e8f0"
INK = "#0d1526"
ACCENTS = {
    "pink":   ("#dd0f68", "#ffe5ee"),   # メインカラー（2026-07-19 青から変更）
    "violet": ("#6d4fe0", "#f0ebff"),
    "teal":   ("#0e9d8a", "#e2f7f3"),
    "amber":  ("#b4761a", "#fdf2dd"),
    "rose":   ("#d0455e", "#fdeaee"),
}

# トピックごとの基調色。分類が色で分かるようにする
TOPIC_HUE = {
    "models": "pink",
    "tools": "violet",
    "dev": "teal",
    "business": "pink",
    "policy": "amber",
    "research": "violet",
    "infra": "teal",
    "japan": "rose",
    "default": "pink",
}

VARIANTS = 16  # トピックあたりの枚数。600件に割り当てて同じ絵が並ばない程度


def rnd(seed: str):
    """seedから決定的な擬似乱数列を作る（毎回同じ絵が出るように）"""
    h = hashlib.sha256(seed.encode()).digest()
    i = 0

    def nxt(lo: float, hi: float) -> float:
        nonlocal i, h
        if i >= len(h) - 2:
            h = hashlib.sha256(h).digest()
            i = 0
        v = (h[i] << 8 | h[i + 1]) / 65535.0
        i += 2
        return lo + (hi - lo) * v
    return nxt


def frame(body: str) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="{W}" height="{H}" role="img">'
        f'<rect width="{W}" height="{H}" fill="{BG}"/>{body}'
        f'<rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" fill="none" '
        f'stroke="{LINE}"/></svg>'
    )


# --- トピック別の意匠 -------------------------------------------------
# 何を表しているかが一目で分かる形にする。抽象芸術にしない。

def art_models(r, c, soft):
    """新モデル: 積み重なる層。世代が重なっていくイメージ"""
    p = []
    n = int(r(4, 7))
    for i in range(n):
        y = 120 + i * (300 / n)
        w = 520 - i * r(30, 60)
        x = (W - w) / 2 + r(-40, 40)
        op = 0.15 + 0.13 * i
        p.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="28" '
                 f'rx="6" fill="{c}" opacity="{op:.2f}"/>')
    return "".join(p)


def art_tools(r, c, soft):
    """業務ツール: 手順のチェックリスト"""
    p = [f'<rect x="300" y="110" width="424" height="356" rx="10" '
         f'fill="#ffffff" stroke="{LINE}"/>']
    for i in range(6):
        y = 160 + i * 52
        done = r(0, 1) > 0.35
        p.append(f'<rect x="336" y="{y-13}" width="26" height="26" rx="5" '
                 f'fill="{soft if done else "#ffffff"}" stroke="{c}"/>')
        if done:
            p.append(f'<path d="M342 {y} l6 7 l12 -14" fill="none" '
                     f'stroke="{c}" stroke-width="3" stroke-linecap="round"/>')
        p.append(f'<rect x="382" y="{y-7}" width="{int(r(160,300))}" '
                 f'height="12" rx="6" fill="{INK}" opacity="0.14"/>')
    return "".join(p)


def art_dev(r, c, soft):
    """開発・実装: つながったノード。処理の流れ"""
    pts = [(180 + i * 140, 288 + r(-110, 110)) for i in range(6)]
    p = []
    for a, b in zip(pts, pts[1:]):
        p.append(f'<line x1="{a[0]:.0f}" y1="{a[1]:.0f}" x2="{b[0]:.0f}" '
                 f'y2="{b[1]:.0f}" stroke="{c}" stroke-width="2" opacity="0.5"/>')
    for x, y in pts:
        p.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r(10,20):.0f}" '
                 f'fill="{soft}" stroke="{c}" stroke-width="2"/>')
    return "".join(p)


def art_business(r, c, soft):
    """企業動向: 推移の棒グラフ"""
    p = [f'<line x1="200" y1="440" x2="824" y2="440" stroke="{LINE}" stroke-width="2"/>']
    n = 8
    for i in range(n):
        h = r(60, 250)
        x = 220 + i * (600 / n)
        p.append(f'<rect x="{x:.0f}" y="{440-h:.0f}" width="{560/n-16:.0f}" '
                 f'height="{h:.0f}" rx="4" fill="{c}" opacity="{0.25+0.06*i:.2f}"/>')
    return "".join(p)


def art_policy(r, c, soft):
    """規制・法制度: 条文の並ぶ書面"""
    p = [f'<rect x="330" y="96" width="364" height="384" rx="6" '
         f'fill="#ffffff" stroke="{LINE}"/>',
         f'<rect x="330" y="96" width="364" height="10" fill="{c}" opacity="0.5"/>']
    y = 150
    for _ in range(11):
        w = r(120, 300)
        p.append(f'<rect x="366" y="{y}" width="{w:.0f}" height="9" rx="4" '
                 f'fill="{INK}" opacity="0.13"/>')
        y += 28
    return "".join(p)


def art_research(r, c, soft):
    """研究動向: 散布と傾向線"""
    p = [f'<line x1="200" y1="450" x2="824" y2="450" stroke="{LINE}" stroke-width="2"/>',
         f'<line x1="200" y1="450" x2="200" y2="110" stroke="{LINE}" stroke-width="2"/>']
    for i in range(26):
        t = i / 25
        x = 220 + t * 580
        y = 430 - t * 280 + r(-45, 45)
        p.append(f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{r(4,8):.0f}" '
                 f'fill="{c}" opacity="0.45"/>')
    p.append(f'<line x1="220" y1="430" x2="800" y2="150" stroke="{c}" '
             f'stroke-width="2.5" stroke-dasharray="8 6"/>')
    return "".join(p)


def art_infra(r, c, soft):
    """半導体・インフラ: 基板の配線"""
    p = [f'<rect x="392" y="216" width="240" height="144" rx="8" '
         f'fill="{soft}" stroke="{c}" stroke-width="2"/>']
    for i in range(9):
        y = 240 + i * 12
        p.append(f'<line x1="392" y1="{y}" x2="{r(200,340):.0f}" y2="{y}" '
                 f'stroke="{c}" stroke-width="1.5" opacity="0.4"/>')
        p.append(f'<line x1="632" y1="{y}" x2="{r(684,824):.0f}" y2="{y}" '
                 f'stroke="{c}" stroke-width="1.5" opacity="0.4"/>')
    for i in range(6):
        x = 420 + i * 36
        p.append(f'<line x1="{x}" y1="216" x2="{x}" y2="{r(120,180):.0f}" '
                 f'stroke="{c}" stroke-width="1.5" opacity="0.35"/>')
        p.append(f'<line x1="{x}" y1="360" x2="{x}" y2="{r(396,460):.0f}" '
                 f'stroke="{c}" stroke-width="1.5" opacity="0.35"/>')
    return "".join(p)


def art_japan(r, c, soft):
    """国内動向: 中心から広がる円弧"""
    cx, cy = W / 2, H / 2 + 40
    p = []
    for i in range(6):
        rad = 60 + i * 46
        p.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{rad}" fill="none" '
                 f'stroke="{c}" stroke-width="2" opacity="{0.5-0.06*i:.2f}"/>')
    p.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="26" fill="{c}" opacity="0.7"/>')
    return "".join(p)


def art_default(r, c, soft):
    """分類なし: 情報の断片が集まっている状態"""
    p = []
    for i in range(14):
        x, y = r(180, 760), r(120, 420)
        w = r(60, 170)
        p.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="14" '
                 f'rx="7" fill="{c}" opacity="{r(0.12,0.4):.2f}"/>')
    return "".join(p)


ART = {
    "models": art_models, "tools": art_tools, "dev": art_dev,
    "business": art_business, "policy": art_policy, "research": art_research,
    "infra": art_infra, "japan": art_japan, "default": art_default,
}


def main() -> int:
    force = "--force" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    made = skipped = 0
    for topic, fn in ART.items():
        hue = TOPIC_HUE[topic]
        for v in range(VARIANTS):
            name = f"news-{topic}-{v:02d}.svg"
            path = OUT / name
            if path.exists() and not force:
                skipped += 1
                continue
            seed = f"{topic}:{v}"
            r = rnd(seed)
            # 同じトピックでも枚数の1/4は隣の色にして、単調さを避ける
            keys = list(ACCENTS)
            c, soft = ACCENTS[hue] if v % 4 else ACCENTS[keys[v % len(keys)]]
            path.write_text(frame(fn(r, c, soft)), encoding="utf-8")
            made += 1
    print(f"=== 生成{made} / スキップ{skipped}（{len(ART)}トピック × {VARIANTS}枚）===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

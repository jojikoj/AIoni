"""週次の自己点検レポートを作る。

「作りっぱなしにしない」ための仕組み。
検索順位そのものは Search Console を見ないと分からないが、
**順位が上がらない原因の多くはサイト側で先に検知できる**。

ここで見るのは次の4点。

1. 薄いページ（文字数が足りず、検索でもAIでも拾われにくい）
2. 本文からの言及（本文中のリンクは文脈のある推薦として回遊に効く）
3. トピックの偏り（同じタグばかりで、取れる検索語が広がらない）
4. 更新の停滞（何日書いていないか）

出力は案件フォルダの Markdown。次に書くべき記事の候補まで出す。

    python3 tools/weekly_review.py
"""
from __future__ import annotations

import collections
import datetime
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "content" / "articles"
OUT_DIR = (pathlib.Path.home() / "claude_AIR/TOEcompany/コンテンツ部"
           / "案件/AIの鬼/週次レポート")

# 特集記事の目標文字数。これを下回ると検索でもAI回答でも引用されにくい。
MIN_CHARS = 2000
# 1本あたり最低これだけは他記事から張られていてほしい
MIN_INBOUND = 1


def plain(md: str) -> str:
    """front matter と記法を落として本文の文字数を数えるための素文字列。"""
    md = re.sub(r"^---\n.*?\n---\n", "", md, flags=re.S)
    md = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", md)   # リンクは表示文字だけ残す
    md = re.sub(r"[#*`|>\-]", "", md)
    return re.sub(r"\s", "", md)


def front(md: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", md, flags=re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def main() -> int:
    arts = {}
    for f in sorted(ARTICLES.glob("*.ja.md")):
        md = f.read_text(encoding="utf-8")
        slug = f.name.replace(".ja.md", "")
        arts[slug] = {
            "fm": front(md),
            "chars": len(plain(md)),
            "links": set(re.findall(r"\]\(/articles/([^/]+)/\)", md)) - {slug},
        }

    inbound = collections.Counter()
    for a in arts.values():
        for t in a["links"]:
            inbound[t] += 1

    today = datetime.date.today()
    L: list[str] = [
        f"# AIの鬼 週次レポート — {today}", "",
        f"特集記事 **{len(arts)}本**", "",
    ]

    # --- 1. 薄いページ ---
    thin = [(s, a) for s, a in arts.items() if a["chars"] < MIN_CHARS]
    L += ["## 1. 薄いページ", ""]
    if thin:
        L += [f"{MIN_CHARS}字未満が {len(thin)}本。加筆対象。", ""]
        L += [f"- `{s}` — {a['chars']}字" for s, a in thin]
    else:
        L += [f"なし（全記事が{MIN_CHARS}字以上）"]
    L += [""]

    # --- 2. 本文からの言及 ---
    #
    # 数えているのは「記事の本文中に置かれたリンク」だけ。ページ下部の
    # 「あわせて読む」は build.py が全記事に自動で付けるので、ここには入らない。
    #
    # 2026-08-01 実測: 被リンクの有無と検索表示率にはほとんど差が無かった
    # （リンクあり38% / なし32%）。ゼロだから検索に出ない、という関係では
    # ないので「孤立＝評価が伸びない」とは書かない。本文中のリンクは
    # 文脈のある推薦として読者の回遊に効く、という位置づけで見る。
    orphan = [s for s in arts if inbound[s] < MIN_INBOUND]
    L += ["## 2. 本文から言及されていない記事", ""]
    if orphan:
        L += [f"本文中に他記事へのリンクが {MIN_INBOUND}本未満のもの。"
              "ページ下部の「あわせて読む」は全記事に自動で付くので、"
              "ここに出ていても関連記事の欄は空ではない。", ""]
        L += [f"- `{s}`（本文からの被リンク {inbound[s]}）" for s in orphan]
    else:
        L += ["なし"]
    L += [""]

    # --- 3. 画像 ---
    #
    # front matter に hero を書いていない記事。画面が空欄になるわけではなく、
    # build.py がカテゴリ別のイラスト(SVG)を当てる。写真に差し替えたい
    # ときの候補一覧として見る（2026-08-01 実測で表示自体は崩れていない）。
    noimg = [s for s, a in arts.items() if not a["fm"].get("hero")]
    L += ["## 3. 写真ではなくイラストが当たっている記事", ""]
    if noimg:
        L += ["front matter に `hero:` が無い記事。表示は崩れず、"
              "カテゴリ別のイラストが自動で入る。写真にしたい場合の候補。", ""]
    L += ([f"- `{s}`" for s in noimg] if noimg else ["なし"]) + [""]

    # --- 4. タグの分布 ---
    tags = collections.Counter(a["fm"].get("tag", "?") for a in arts.values())
    L += ["## 4. タグの分布", ""]
    L += [f"- {t}: {n}本" for t, n in tags.most_common()] + [""]

    # --- 5. 更新の間隔 ---
    dates = sorted(a["fm"].get("date", "") for a in arts.values() if a["fm"].get("date"))
    if dates:
        try:
            last = datetime.date.fromisoformat(dates[-1])
            gap = (today - last).days
            L += ["## 5. 更新状況", "",
                  f"最終公開: {last}（{gap}日前）",
                  "", "**2週間空くと検索エンジンの巡回頻度が落ちる。**"
                  if gap >= 14 else ""]
        except ValueError:
            pass
    L += [""]

    # --- 6. ニュース側の消化状況 ---
    #
    # 数えるのは body_long。サイト（build.py / news_article.html）が実際に
    # 表示するのはこのフィールドで、body_ja は表示されない。
    #
    # 2026-08-01 まで body_ja を数えていた。実測すると body_ja は 0件、
    # body_long は 445件で、レポートはずっと「0%」と報告していたことになる。
    # 日次スクリプト(daily.sh)は 7-30 に同じ誤りを直しているが、
    # こちらが取り残されていた。数字が動いていないのに気づけないのが、
    # いちばん厄介な壊れ方なので、何を数えているかをここに残しておく。
    #
    # 素材の無いもの（body_skip）は、配信元が本文を出しておらず
    # 解説を書きようがない。処理待ちと区別して数える。
    news = ROOT / "data" / "news.json"
    if news.exists():
        d = json.loads(news.read_text(encoding="utf-8"))
        items = d.get("items", [])
        body = sum(1 for i in items if (i.get("body_long") or "").strip())
        skip = sum(1 for i in items
                   if not (i.get("body_long") or "").strip() and i.get("body_skip"))
        pending = len(items) - body - skip
        L += ["## 6. ニュースの解説生成", "",
              f"{len(items)}件中 **{body}件**に自社の解説あり"
              f"（{body * 100 // max(len(items), 1)}%）",
              "",
              f"- 解説あり（検索対象）: {body}件",
              f"- 素材が取れず書けない: {skip}件（配信元が本文を出していない）",
              f"- 未処理（これから書ける）: {pending}件",
              "", "解説の無いページは noindex にして sitemap からも外している"
              "ので、検索結果を薄めることはない。ただし未処理が積み上がると"
              "自社の解説がある記事の割合が下がる。", ""]

        # --- 6-2. 解説の段落数（検索結果の説明文がここで決まる） ---
        #
        # build.py の news_meta は、解説の「2段落目＝AIの鬼の視点」を
        # description に出す。2段落目が無いページは1段落目（事実の言い直し）に
        # 落ち、配信元の要約と区別がつかなくなる。
        #
        # 2026-08-02 実測: 解説445件のうち131件(29.4%)が1段落しかなく、
        # 前日入れた「2段落目を出す」修正が3割に効いていなかった。生成
        # プロンプトは「2〜4段落」を指定しているが、機械では見ていなかった。
        # 同じことが再発したときに気づけるよう、ここで毎週数える。
        def _paras(txt: str) -> list[str]:
            ps = [x.strip() for x in (txt or "").split("\n\n") if x.strip()]
            if len(ps) < 2:
                ps = [x.strip() for x in (txt or "").split("\n") if x.strip()]
            return ps

        withbody = [i for i in items if (i.get("body_long") or "").strip()]
        single = [i for i in withbody if len(_paras(i["body_long"])) < 2]
        short = [i for i in withbody
                 if len(re.sub(r"\s", "", i["body_long"])) < 720]
        ratio = len(single) * 100 // max(len(withbody), 1)
        L += ["### 解説の段落数（説明文の質に直結）", "",
              f"- 1段落しかない: **{len(single)}件**（{ratio}%）"
              f"{'  ⚠️ 検索結果に「事実の言い直し」が出ている' if single else ''}",
              f"- 目標下限720字を下回る: {len(short)}件", "",
              "1段落しかないものは、検索結果の説明文が配信元の要約と"
              "区別のつかない文になる。10%を超えたら解説を作り直すこと"
              "（対象の選び方は 2026-08-01 の作業記録 18節）。", ""]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{today}.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"✅ {out}")
    print(f"   薄い{len(thin)} / 本文からの言及なし{len(orphan)} / イラスト{len(noimg)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""週次の自己点検レポートを作る。

「作りっぱなしにしない」ための仕組み。
検索順位そのものは Search Console を見ないと分からないが、
**順位が上がらない原因の多くはサイト側で先に検知できる**。

ここで見るのは次の4点。

1. 薄いページ（文字数が足りず、検索でもAIでも拾われにくい）
2. 内部リンクの孤立（どこからもリンクされていない記事は評価が伸びない）
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

    # --- 2. 内部リンクの孤立 ---
    orphan = [s for s in arts if inbound[s] < MIN_INBOUND]
    L += ["## 2. 他記事から張られていない記事", ""]
    if orphan:
        L += ["孤立した記事は検索評価が伸びない。関連記事から言及を足す。", ""]
        L += [f"- `{s}`（被リンク {inbound[s]}）" for s in orphan]
    else:
        L += ["なし"]
    L += [""]

    # --- 3. 画像 ---
    noimg = [s for s, a in arts.items() if not a["fm"].get("hero")]
    L += ["## 3. カバー画像のない記事", ""]
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
    news = ROOT / "data" / "news.json"
    if news.exists():
        d = json.loads(news.read_text(encoding="utf-8"))
        items = d.get("items", [])
        body = sum(1 for i in items if i.get("body_ja"))
        L += ["## 6. ニュースの本文生成", "",
              f"{len(items)}件中 {body}件が本文つき"
              f"（{body * 100 // max(len(items), 1)}%）",
              "", "本文のないページは薄いページとして評価されるため、"
              "未処理を残さないこと。", ""]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{today}.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"✅ {out}")
    print(f"   薄い{len(thin)} / 孤立{len(orphan)} / 画像なし{len(noimg)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

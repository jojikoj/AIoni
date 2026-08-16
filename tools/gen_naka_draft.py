"""「中の鬼」の下書きを、当社の実ログだけを素材にして作る。

なぜ作ったか（2026-08-15）:
    実測で、このサイトで一番読まれているのは論文解説でもニュースでもなく
    「中の鬼」だった。28日で40表示・8クリック＝**CTR 20%**。
    サイト全体の平均（1,987表示・62クリック＝3.1%）の6倍。
    /shippai/（失敗の鬼）も31表示・4クリック＝12.9%で続く。
    一方、毎日自動生成している論文解説は238本中160本が
    公開2週間を過ぎても表示ほぼ0のまま積み上がっていた。

    ところが日次（daily.sh）は「中の鬼は自社の実測が要るので自動生成しない」
    という理由で、一番効いている棚だけ手つかずだった。人が書かない限り
    増えないので、実際7月から止まっていた。

    素材が無いわけではない。**このサイト自体が毎日出している実測がある**。
    Search Console の推移、日次の成否、記事本数、失敗したcronの記録。
    それを素材にすれば、捏造ゼロで中の鬼が書ける。

公開の扱い（2026-08-16 変更）:
    当初は下書きだけ（content/_naka_draft/）を出し、人が直してから公開する
    設計にしていた。**今後も人は記事を書かない**方針が確定したため、
    下書きのまま置くと永久に公開されない。検査を通ったものは自動で公開する。

    そのぶん検査は publish_daily.py と同じものをかける
    （水増し表現ゼロ・素材に無い数字ゼロ）。落ちたものは公開せず
    content/_naka_draft/ に残る。1本落ちても構わない。

素材（すべて当社の実ファイル。外から数字を持ち込まない）:
    - data/gsc_history.tsv     … 表示・クリック・順位の推移
    - data/daily_stats.tsv     … ニュース件数・本文件数・記事本数
    - git log                  … その週に実際に何を直したか
    - 直近の実測レビュー        … 何が問題だと分かったか

実行:
    python3 tools/gen_naka_draft.py            # 下書きを1本
    python3 tools/gen_naka_draft.py --print    # 標準出力に出すだけ
"""
from __future__ import annotations

import datetime
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "content" / "articles"
# 検査に落ちたものだけがここに残る（公開されなかった記録として）。
DRAFTS = ROOT / "content" / "_naka_draft"
HISTORY = ROOT / "data" / "gsc_history.tsv"
STATS = ROOT / "data" / "daily_stats.tsv"
REVIEW_DIR = (pathlib.Path.home()
              / "claude_AIR/TOEcompany/コンテンツ部/案件/AIの鬼/実測レビュー")

# 下書きを作る間隔。毎日出しても人が直しきれず、溜まった下書きは読まれない。
EVERY_N_DAYS = 7


def tail(path: pathlib.Path, n: int) -> str:
    if not path.exists():
        return "（記録なし）"
    lines = path.read_text(encoding="utf-8").splitlines()
    return "\n".join(lines[-n:])


def recent_commits(days: int = 7) -> str:
    try:
        r = subprocess.run(
            ["git", "log", f"--since={days} days ago", "--pretty=%ad %s",
             "--date=short"],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
        return r.stdout.strip() or "（この期間の変更なし）"
    except (OSError, subprocess.SubprocessError):
        return "（取得できず）"


def latest_review() -> str:
    if not REVIEW_DIR.exists():
        return "（レビューなし）"
    files = sorted(REVIEW_DIR.glob("*.md"))
    if not files:
        return "（レビューなし）"
    return files[-1].read_text(encoding="utf-8")[:4000]


def build_prompt() -> str:
    return f"""あなたは「AIの鬼」というメディアの「中の鬼」というコーナーの書き手です。
株式会社TOEという福岡の会社が、自社でAIを動かしている記録を書いています。

## このコーナーの性格

読み物です。ノウハウ記事ではありません。AIと毎日やり合っている人間の
手触りを書く場所です。実測で、このコーナーだけクリック率が20%あります
（サイト平均は3.1%）。読者は数字の裏にある「で、実際どうだったの」を
読みに来ています。

## 書き方の約束

- 一人称。かしこまらない。ただし読者を茶化さない。
- **数字は下の素材にあるものだけ使う。** 無い数字は書かない。
  「約」「およそ」で誤魔化さない。素材に無ければその話をしない。
- **自分で計算した数字を書かない。** 「5倍」「3割減」「1本あたり◯件」など、
  素材の数字どうしを割ったり掛けたりして作った値は書けません
  （検査で弾かれ、記事ごと捨てられます）。素材に書いてある表記のまま引く。
  比較したいときは「40と8」のように、両方の実数を並べて読者に見せること。
- うまくいった話より、外した話・意外だった話を優先する。
- 教訓で締めない。読者に「あなたも〜しましょう」と言わない。
- 1,500〜2,500字。薄い長文にしない。書くことが尽きたら短く終える。
- 見出しは2〜4個。表は要らない（このコーナーは読み物なので）。
- 冒頭3行で「何の話か」が分かるようにする。

## 出力の形式

front matter から本文まで、そのまま .md ファイルになる形で出してください。
説明や前置きは一切書かないこと。

---
title: （25〜40字。問いか、意外な事実。「〜してみた」は使わない）
excerpt: （100〜150字。何が起きたかを具体的に）
tag: 中の鬼
author: AIの鬼 編集部
date: {datetime.date.today()}
---

（本文）

## 素材1: 検索の実測（Search Console。表示・クリック・平均順位）

```
{tail(HISTORY, 21)}
```

## 素材2: 日次の生産量（ニュース収集件数・要約本文件数・記事本数）

```
{tail(STATS, 14)}
```

## 素材3: この1週間に実際に直したこと（gitの記録）

```
{recent_commits(7)}
```

## 素材4: 直近の実測レビュー（何が問題だと分かったか）

```
{latest_review()}
```

## 今回書いてほしいこと

素材の中から、**自分でも意外だった一点**を選んで、それだけを書いてください。
全部を要約しないこと。数字の羅列にしないこと。
「毎日せっせと作っていたものが、実は読まれていなかった」というような、
書いていて痛い話ほどこのコーナーには合います。
"""


def main() -> int:
    if "--print" not in sys.argv:
        # 週1本まで。直近に出した中の鬼があれば今日は作らない。
        # 素材（このサイト自身の実測）は1週間でようやく動くので、
        # 毎日書かせても同じ話の言い換えになる。
        # ⚠️ ファイルの mtime では判定しない。git で取り直すと全ファイルの
        # mtime が同じ日に揃うので、既存21本があるだけで「今日は作らない」に
        # なってしまう。front matter の date（実際の公開日）で見る。
        latest = None
        for p in ARTICLES.glob("naka-*.ja.md"):
            m = re.search(r"^date:\s*['\"]?(\d{4}-\d{2}-\d{2})",
                          p.read_text(encoding="utf-8"), re.M)
            if m:
                d = datetime.date.fromisoformat(m.group(1))
                latest = d if latest is None or d > latest else latest
        if latest:
            age = (datetime.date.today() - latest).days
            if age < EVERY_N_DAYS:
                print(f"   中の鬼は{age}日前（{latest}）に出したばかりなので今日は作らない")
                return 0

    model = os.environ.get("AIONI_ARTICLE_MODEL", "sonnet")
    try:
        # `--tools ""` は必須。付けないと CLI が「記事を書く」を作業として
        # 解釈し、自分で content/ にファイルを置いて標準出力には報告だけ返す。
        r = subprocess.run(["claude", "-p", "--model", model, "--tools", ""],
                           input=build_prompt(), capture_output=True,
                           text=True, timeout=900)
    except FileNotFoundError:
        print("   ⚠️ claude CLI が見つからない")
        return 1
    except subprocess.TimeoutExpired:
        print("   ⚠️ 生成がタイムアウトした")
        return 1
    if r.returncode != 0:
        print(f"   ⚠️ 生成に失敗（rc={r.returncode}）: {r.stderr.strip()[:200]}")
        return 1

    text = r.stdout.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n```\s*$", "", text)
    if not text.startswith("---"):
        print("   ⚠️ front matter で始まっていないので捨てる")
        return 1

    if "--print" in sys.argv:
        print(text)
        return 0

    m = re.search(r"^title:\s*(.+)$", text, re.M)
    title = m.group(1).strip() if m else "（無題）"

    # 検査。中の鬼は読み物なので表もまとめも求めないが、
    # 「水増し表現」と「素材に無い数字」だけは他の棚と同じ基準で弾く。
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from publish_daily import PADDING, unverified_numbers, FACTS, auto_facts
    body = text.split("---", 2)[2] if text.count("---") >= 2 else text
    material = "\n".join([FACTS, auto_facts(), tail(HISTORY, 30),
                          tail(STATS, 20), recent_commits(7), latest_review()])
    pad = [p for p in PADDING if p in body]
    bad = unverified_numbers(body, material)
    chars = len(re.sub(r"\s", "", body))
    reason = ""
    if pad:
        reason = f"水増し表現 {pad}"
    elif bad:
        reason = f"裏の取れない数字 {bad[:6]}"
    elif chars < 1000:
        # 中の鬼は読み物なので、短いこと自体は欠点ではない
        # （[[feedback_no_padding_over_length]]：薄い長文より短い記事）。
        # 1,000字を切ったら、さすがに1本の記事として成立していないとみなす。
        reason = f"本文が短い（{chars}字）"

    DRAFTS.mkdir(parents=True, exist_ok=True)
    if reason:
        out = DRAFTS / f"naka-rejected-{datetime.date.today()}.md"
        out.write_text(text, encoding="utf-8")
        print(f"   検査に落ちたので公開しない: {reason}")
        print(f"   {out}")
        return 0

    slug = re.sub(r"[^a-z0-9]+", "-",
                  (re.search(r"^slug:\s*(.+)$", text, re.M).group(1).strip()
                   if re.search(r"^slug:", text, re.M)
                   else f"naka-{datetime.date.today()}")).strip("-")
    if not slug.startswith("naka"):
        slug = f"naka-{slug}"
    dest = ARTICLES / f"{slug}.ja.md"
    if dest.exists():
        slug = f"{slug}-2"
        dest = ARTICLES / f"{slug}.ja.md"
    dest.write_text(text, encoding="utf-8")
    print(f"   中の鬼を公開: {title}（{chars}字）")
    print(f"   {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

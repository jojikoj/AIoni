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

公開しない:
    出すのは下書きだけ（content/_naka_draft/）。中の鬼は語り口が
    そのまま媒体の顔になる棚なので、最後は人が直してから公開する。
    ここが自動で本番に出ると、一番効いている棚の質が真っ先に落ちる。

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
        DRAFTS.mkdir(parents=True, exist_ok=True)
        # 直近の下書きが手つかずで残っているなら、増やさない。
        existing = sorted(DRAFTS.glob("*.md"))
        if existing:
            newest = datetime.date.fromtimestamp(existing[-1].stat().st_mtime)
            age = (datetime.date.today() - newest).days
            if age < EVERY_N_DAYS:
                print(f"   中の鬼の下書きは{age}日前に作ったものが未使用のため今日は作らない"
                      f"（{existing[-1].name}）")
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
    out = DRAFTS / f"naka-draft-{datetime.date.today()}.md"
    out.write_text(text, encoding="utf-8")
    print(f"   中の鬼の下書き: {title}")
    print(f"   {out}")
    print("   → 読んで直したら content/articles/naka-<slug>.ja.md に移すと公開されます")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

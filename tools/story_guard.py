#!/usr/bin/env python3
"""実話をもとにした記事から、客・会社・人・業種が特定できる語を機械的に落とす。

小嶋さんの指示（2026-11-01）: 「絶対に、企業名や、個人名、会社、業務内容が特定できるような
内容にしないこと」。記事の材料は作業履歴とメールなので、書き手（AI）に任せるだけでは
いつか漏れる。公開は取り消せないので、ここは疑わしければ止める（fail closed）。

⚠️ このリポジトリは公開なので、客の名前の一覧をここに書かない。
   一覧は claude_AIR の _社外秘 に置き（build_blocklist.py）、ここは読むだけにする。
   一覧が読めないときは「検査できない」として不合格にする。

見るもの:
  1. 一覧（客・取引先・社員・業者・案件）にある名前
  2. 材料の中の固有名（メールアドレス・ドメイン・「〇〇様」「〇〇さん」「株式会社〇〇」）
  3. 都道府県・主要都市の名前
  4. 特定につながる細部（日付・時刻・金額・電話番号・郵便番号）
  5. 許可していない外部リンク

    python3 tools/story_guard.py <記事.md> [--material 材料.txt] [--allow-host www.php.net]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

BLOCKLIST = (Path.home() / "claude_AIR/TOEcompany/メディア事業部/案件/AIの鬼"
             / "_社外秘/週次記事/blocklist.txt")

PLACES = (
    "北海道 青森 岩手 宮城 秋田 山形 福島 茨城 栃木 群馬 埼玉 千葉 東京 神奈川 新潟 富山 石川 福井 "
    "山梨 長野 岐阜 静岡 愛知 三重 滋賀 京都 大阪 兵庫 奈良 和歌山 鳥取 島根 岡山 広島 山口 徳島 "
    "香川 愛媛 高知 福岡 佐賀 長崎 熊本 大分 宮崎 鹿児島 沖縄 九州 四国 関西 関東 東北 北陸 中国地方 "
    "博多 天神 札幌 仙台 横浜 名古屋 神戸 北九州"
).split()

# 材料から拾った語のうち、普通の言葉として記事に出てよいもの
COMMON = set(
    "お客 担当 担当者 先方 皆 みな お疲れ お世話 ご担当 こちら そちら 小さな 大きな 様子 同様 模様 "
    "仕様 多様 異様 別様 今様 神様 王様 代表 顧客 社員 利用者 管理者 責任者 関係者 取引先 "
    "読者 皆さん 一般 お客".split()
)

PATTERNS = [
    ("日付", r"(?<![0-9])[0-9]{1,2}月[0-9]{1,2}日|(?<![0-9/.])[0-9]{1,2}/[0-9]{1,2}(?![0-9/])"),
    ("時刻", r"(?<![0-9])[0-9]{1,2}:[0-9]{2}(?![0-9])|(?<![0-9])[0-9]{1,2}時[0-9]{1,2}分"),
    ("金額", r"[0-9][0-9,]*(?:万|千)?円|[0-9][0-9,]*万円"),
    ("電話番号", r"(?<![0-9])0[0-9]{1,4}-[0-9]{1,4}-[0-9]{3,4}(?![0-9])"),
    ("郵便番号", r"〒|(?<![0-9])[0-9]{3}-[0-9]{4}(?![0-9])"),
    ("メール", r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
    ("法人格", r"株式会社|有限会社|合同会社|医療法人|社会福祉法人|一般社団法人"),
]


def norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).casefold()


def load_blocklist() -> list[str] | None:
    if not BLOCKLIST.exists():
        return None
    return [l.strip() for l in BLOCKLIST.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def names_in_material(text: str) -> set[str]:
    """材料に出てくる固有名を拾う。一覧に無い新しい相手もここで止まる。"""
    found: set[str] = set()
    for m in re.findall(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})", text):
        found.add(m)
        found.add(m.split(".")[0])
    for m in re.findall(r"https?://(?:www\.)?([A-Za-z0-9.\-]+\.[a-z]{2,})", text):
        found.add(m)
    for m in re.findall(r"([一-龥ァ-ヶー]{2,8})(?:様|さん)", text):
        found.add(m)
    # 法人格と名前は同じ行にある。\s にすると改行をまたいで、メール署名の
    # 「…です\n株式会社〇〇」から「です」を会社名として拾ってしまい、毎回不合格になる。
    for m in re.findall(r"(?:株式会社|有限会社|合同会社)[ \t　]*([一-龥ぁ-んァ-ヶーA-Za-z0-9&]{2,20})", text):
        found.add(m)
    for m in re.findall(r"([一-龥ぁ-んァ-ヶーA-Za-z0-9&]{2,20})[ \t　]*(?:株式会社|有限会社|合同会社)", text):
        # 前に付く語は、名前でなく文末（です・ます）や説明語（制作会社）のことがある
        if not _is_plain_word(m):
            found.add(m)
    # 公開の技術名・媒体名は固有名として止めない
    allow = {"php.net", "github.com", "wordpress.org", "ai-oni.com", "gmail.com"}
    return {f for f in found if f not in COMMON and f.lower() not in allow and len(f) >= 2
            and not f.endswith("会社")}


def _is_plain_word(word: str) -> bool:
    """名前ではなく普通の言葉（「です」「会社」「制作会社」）なら True。

    法人格の前から拾った語は、名前でなく文の切れ端や説明語のことがある。これを固有名として
    止めると、「会社」と書いただけの記事が毎回落ちる。ひらがなだけの短い語（です・ます・ください）と、
    「会社」で終わる語（会社・制作会社・親会社）は普通の言葉として扱う。
    一覧（blocklist.txt）にある名前は別に検査しているので、ここを緩めても名前は止まる。
    """
    return bool(re.fullmatch(r"[ぁ-ん]{1,4}", word)) or word.endswith("会社")


def check(text: str, material: str = "", allow_hosts: tuple[str, ...] = ()) -> list[dict]:
    """問題の一覧を返す。空なら合格。"""
    problems: list[dict] = []
    # 自社記事への内部リンクの slug は読者が読む文字ではないので、名前の検査から外す
    t = norm(re.sub(r"\(/articles/[a-z0-9\-]+/?\)", "()", text))

    def hit(word: str) -> bool:
        w = norm(word)
        if re.fullmatch(r"[a-z0-9.\-_& ]+", w):
            return re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", t) is not None
        return w in t

    blocklist = load_blocklist()
    if blocklist is None:
        problems.append({"kind": "一覧なし", "word": str(BLOCKLIST),
                         "why": "名前の一覧が読めないので検査できない"})
    else:
        for word in blocklist:
            if hit(word):
                problems.append({"kind": "名前", "word": word, "why": "客・取引先・社員・業者・案件の名前"})

    if material:
        known = {p["word"] for p in problems}
        for word in sorted(names_in_material(material)):
            if word not in known and hit(word):
                problems.append({"kind": "材料の固有名", "word": word, "why": "材料に出てくる名前"})

    for place in PLACES:
        if place in t:
            problems.append({"kind": "地名", "word": place, "why": "地域が絞れる"})

    # front matter の date は検査しない（公開日そのものなので）
    body = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.S)
    plain = re.sub(r"\((?:https?://|/)[^)]*\)", "()", body)
    for kind, pat in PATTERNS:
        for m in re.finditer(pat, unicodedata.normalize("NFKC", plain)):
            problems.append({"kind": kind, "word": m.group(0), "why": "特定につながる細部"})

    for host in re.findall(r"https?://([A-Za-z0-9.\-]+)", body):
        if host not in allow_hosts and not host.endswith("ai-oni.com"):
            problems.append({"kind": "外部リンク", "word": host, "why": "許可していない外部リンク"})
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("article")
    ap.add_argument("--material", default="")
    ap.add_argument("--allow-host", action="append", default=[])
    args = ap.parse_args()
    text = Path(args.article).read_text(encoding="utf-8")
    material = Path(args.material).read_text(encoding="utf-8") if args.material else ""
    problems = check(text, material, tuple(args.allow_host))
    print(json.dumps(problems, ensure_ascii=False, indent=1))
    print(f"{'不合格' if problems else '合格'}（{len(problems)}件）", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

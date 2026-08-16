"""既に立っている記事を、実測で拾えている検索語に合わせて厚くする。

なぜ作ったか（2026-08-16）:
    商用クエリを実測で洗うと、24語のうち14語は**すでに自社記事が立っている**。

      aiエージェント 総務      → /articles/ai-agent-backoffice/（61位）
      ai開発 見積もり 費用 内訳 → /articles/ai-cost-structure/（100位）
      ai 総務 導入 スタート    → /articles/ai-first-step-smb/（93位）

    ここに新しい記事を足すと、今度は自社記事どうしで共食いになる。
    ニュース要約1,187ページが自社記事の前に立つ型を片付けたばかりで、
    同じことを自分でやる意味がない。既存を厚くする方が正しい
    （[[feedback_aeo_content_strategy]]：AEOは量産でなく既存強化）。

    人は記事を書かない方針なので、加筆も自動でやる。

安全側に倒していること:
    - **既存の本文は1文字も変えない。** 追記だけ。書き直させると、
      人が確かめた記述まで作り直されて、何が変わったのか追えなくなる。
    - 追記は「## まとめ」の直前に入れる。まとめが最後に来る型を崩さない。
    - 追記部分にも同じ捏造ガードをかける（素材に無い数字は不合格）。
    - 元ファイルは content/_reinforce_backup/ に退避してから書き換える。
    - 週1本まで。同じ週にあちこち触ると、順位が動いた理由を追えなくなる。

実行:
    python3 tools/reinforce_article.py            # 1本加筆
    python3 tools/reinforce_article.py --dry-run  # 生成と検査だけ
"""
from __future__ import annotations

import datetime
import json
import pathlib
import re
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from publish_daily import (FACTS, gen_with_claude, strip_fence,  # noqa: E402
                           unverified_numbers, PADDING, log, auto_facts)

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "content" / "articles"
QUERIES = ROOT / "data" / "gsc_queries.json"
BACKUP = ROOT / "content" / "_reinforce_backup"
DONE = ROOT / "data" / "reinforced.json"

MIN_ADD_CHARS = 500     # これ未満の追記なら、やる意味がない
MAX_ADD_CHARS = 2500    # 元記事より長い追記はしない
MAX_TRIES = 3


def done() -> dict:
    if DONE.exists():
        try:
            return json.loads(DONE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def targets() -> list[dict]:
    """自社記事が立っている商用クエリのうち、まだ加筆していないもの。"""
    if not QUERIES.exists():
        return []
    d = json.loads(QUERIES.read_text(encoding="utf-8"))
    seen = done()
    out = []
    for a in d.get("commercial", []):
        if not a.get("has_article") or a["q"] in seen:
            continue
        art = next((p for p in a.get("pages", []) if "/articles/" in p), None)
        if not art:
            continue
        slug = art.strip("/").replace("articles/", "")
        path = ARTICLES / f"{slug}.ja.md"
        if not path.exists():
            continue
        a["slug"] = slug
        a["path"] = path
        out.append(a)
    return out


def split_before_matome(text: str) -> tuple[str, str] | None:
    """「## まとめ」の直前で本文を割る。まとめが無い記事は対象外。"""
    m = re.search(r"\n## まとめ", text)
    if not m:
        return None
    return text[: m.start()], text[m.start():]


def build_prompt(q: dict, body: str) -> str:
    return f"""「AIの鬼」（ai-oni.com、株式会社TOE運営）の既存記事に、**追記だけ**をします。

# 状況

この記事は検索語「**{q['q']}**」で{q['imp']}回表示され、最高{q['pos']}位です。
表示は出ているのに読まれる位置にいません。この語で来た人が
「知りたかったのに書いていなかった」と感じる部分を、追記で埋めます。

# あなたが出すもの

**追記する節だけ**を Markdown で出してください。
既存の本文は書き直しません。1文字も触りません。

- `##` の見出しで始まる節を1〜2本。
- {MIN_ADD_CHARS}〜{MAX_ADD_CHARS}字（空白を除く）。
- 検索語「{q['q']}」を見出しか本文にそのまま使う（言い換えない）。
- **素材に無い数字・事実は書かない。** 一般論・相場・推測は禁止。
  素材で埋められないなら `SKIP: 理由` の1行だけを返してください。
- 既存の本文に既に書いてあることを繰り返さない。
- 敬体（です・ます）。
- 表は入れても入れなくてもよい。入れるなら `| 項目 | 数値 |` の形で、
  数字は素材の表記のまま書き写すこと。
- 使ってはいけない言い回し: {' / '.join(PADDING)}

# 既存の本文（これを読んで、書いていないことだけ足す）

{body[:6000]}

# 素材（当社の実測。ここに無い数字は書けません）

{FACTS}

{auto_facts()}

**ファイルには一切書き込まないこと。追記する節のMarkdownだけを返すこと。**
前置き・後書き・コードフェンスで囲まない。
"""


def check_addition(add: str, material: str) -> tuple[bool, str]:
    if not add.startswith("##"):
        return False, "見出しで始まっていない"
    chars = len(re.sub(r"\s", "", add))
    if chars < MIN_ADD_CHARS:
        return False, f"追記が短い（{chars}字）"
    if chars > MAX_ADD_CHARS:
        return False, f"追記が長すぎる（{chars}字）"
    pad = [p for p in PADDING if p in add]
    if pad:
        return False, f"水増し表現 {pad}"
    if re.search(r"\]\((https?://[^)]+)\)", add):
        return False, "外部リンクが入っている"
    bad = unverified_numbers(add, material)
    if bad:
        return False, f"裏の取れない数字 {bad[:6]}"
    return True, f"{chars}字"


def main() -> int:
    dry = "--dry-run" in sys.argv
    today = str(datetime.date.today())
    material = FACTS + "\n" + auto_facts()
    cands = targets()
    if not cands:
        log("加筆対象がない（全部やり済みか、実測がまだ無い）")
        return 0

    for q in cands[:MAX_TRIES]:
        text = q["path"].read_text(encoding="utf-8")
        parts = split_before_matome(text)
        if not parts:
            log(f"  {q['slug']}: 「## まとめ」が無いので見送り")
            continue
        head, tail = parts
        log(f"加筆先: {q['slug']}（お題「{q['q']}」{q['imp']}表示 / {q['pos']}位）")

        add = strip_fence(gen_with_claude(build_prompt(q, head)))
        if not add:
            continue
        if add.startswith("SKIP"):
            log(f"  素材不足で見送り: {add[:120]}")
            continue
        ok, why = check_addition(add, material)
        if not ok:
            log(f"  検査に落ちた: {why}")
            continue

        merged = head.rstrip() + "\n\n" + add.strip() + "\n" + tail
        if dry:
            log(f"  [dry-run] 通った: {q['slug']} に {why} を追記できる")
            return 0

        BACKUP.mkdir(parents=True, exist_ok=True)
        shutil.copy2(q["path"], BACKUP / f"{q['slug']}.{today}.md")
        q["path"].write_text(merged, encoding="utf-8")

        rec = done()
        rec[q["q"]] = {"slug": q["slug"], "date": today,
                       "added_chars": len(re.sub(r"\s", "", add)),
                       "imp_at_write": q["imp"], "pos_at_write": q["pos"]}
        DONE.write_text(json.dumps(rec, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        log(f"  加筆: {q['slug']}（{why}／元は _reinforce_backup/ に退避）")
        return 0

    log("  今週は加筆できるものがなかった")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

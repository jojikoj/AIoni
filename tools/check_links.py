"""記事内の内部リンクが実在するか検査する。

記事を書くときスラッグを間違えると404になるが、
ビルドは通ってしまうため気づけない。デプロイ前にここで落とす。

    python3 tools/check_links.py   # 壊れていれば exit 1
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "content" / "articles"

# 記事以外で存在が保証されているパス
STATIC_PATHS = {
    "/", "/news/", "/launches/", "/papers/", "/articles/",
    "/companies/", "/contact/", "/advertise/", "/faq/", "/topics/",
}


# 日本語記事に紛れ込んではいけない文字。
# 執筆中に韓国語・キリル文字が混入して公開直前まで気づかなかった実例がある
# （「最高성능」など）。目視では見落とすのでここで落とす。
FOREIGN = re.compile(r"[가-힯Ѐ-ӿ฀-๿]")


def check_foreign_chars() -> list[tuple[str, str, str]]:
    bad = []
    for f in sorted(ARTICLES.glob("*.ja.md")):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            m = FOREIGN.search(line)
            if m:
                bad.append((f.name, f"{i}行目: …{line[max(0, m.start() - 15):m.end() + 15]}…",
                            f"日本語記事に紛れ込まない文字「{m.group(0)}」"))
    return bad


def main() -> int:
    slugs = {f.name.replace(".ja.md", "") for f in ARTICLES.glob("*.ja.md")}
    bad = check_foreign_chars()
    for f in sorted(ARTICLES.glob("*.ja.md")):
        for link in re.findall(r"\]\((/[^)]*)\)", f.read_text(encoding="utf-8")):
            m = re.fullmatch(r"/articles/([^/]+)/", link)
            if m:
                if m.group(1) not in slugs:
                    bad.append((f.name, link, "記事が存在しない"))
            elif link not in STATIC_PATHS:
                bad.append((f.name, link, "未知のパス"))

    for name, link, why in bad:
        print(f"NG {name}: {link}  ({why})", file=sys.stderr)
    if bad:
        print(f"\n壊れた内部リンク {len(bad)}件", file=sys.stderr)
        return 1
    print(f"内部リンク OK（記事{len(slugs)}本）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

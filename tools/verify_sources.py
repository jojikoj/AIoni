"""記事が引用している arXiv 論文が、実在してタイトルも一致するかを検証する。

なぜ必要か:
  2026-07-19、記事生成の投入リストを作っておきながらそれを使わず、
  論文タイトルを手で書いて渡す事故が起きた。24本中23本が実在しない論文だった。
  「既存記事との重複チェック」は通過してしまう（存在しないものは重複しない）。
  出典が実在するかは、書いたあとに機械で確かめるしかない。

やること:
  1. 各記事から arXiv ID を抜き出す
  2. arXiv の公式APIで、そのIDの論文が実在するか問い合わせる
  3. 実在すれば、公式のタイトルを取得して記事の記述と突き合わせる

  ネットワークを使うが、arXiv API は無料。運用課金は発生しない。

実行:
    python3 tools/verify_sources.py              # 全記事
    python3 tools/verify_sources.py ai-mars ...  # 指定slugのみ
"""
from __future__ import annotations

import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "content" / "articles"
API = "http://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"

ID_RE = re.compile(r"arXiv:(\d{4}\.\d{4,5})")


def fetch_meta(arxiv_id: str) -> dict | None:
    """arXiv公式APIで論文の実在とタイトルを確認する。"""
    q = urllib.parse.urlencode({"id_list": arxiv_id, "max_results": 1})
    try:
        with urllib.request.urlopen(f"{API}?{q}", timeout=30) as r:
            root = ET.fromstring(r.read())
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    entry = root.find(f"{ATOM}entry")
    if entry is None:
        return None
    title = (entry.findtext(f"{ATOM}title") or "").strip()
    title = re.sub(r"\s+", " ", title)
    # 存在しないIDでも entry が返り、title が "Error" になることがある
    if title.lower().startswith("error"):
        return None
    return {
        "title": title,
        "published": (entry.findtext(f"{ATOM}published") or "")[:10],
    }


def norm(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def main() -> int:
    targets = sys.argv[1:]
    files = sorted(ARTICLES.glob("*.ja.md"))
    if targets:
        files = [f for f in files if f.name.replace(".ja.md", "") in targets]

    ng = 0
    checked = 0
    for f in files:
        text = f.read_text(encoding="utf-8")
        ids = sorted(set(ID_RE.findall(text)))
        if not ids:
            continue
        slug = f.name.replace(".ja.md", "")
        for aid in ids:
            checked += 1
            meta = fetch_meta(aid)
            time.sleep(0.4)          # arXiv APIへの礼儀。連打しない
            if meta is None:
                print(f"❌ {slug}: arXiv:{aid} は実在しない", file=sys.stderr)
                ng += 1
                continue
            if "error" in meta:
                print(f"⚠️ {slug}: arXiv:{aid} 確認できず（{meta['error']}）")
                continue
            # 記事本文に原題が引用されていれば、単語の重なりで一致を見る。
            # 邦題だけの記事もあるため、原題が無いこと自体は不備にしない。
            words = norm(meta["title"])
            if len(words & norm(text)) < max(3, len(words) // 3):
                print(f"⚠️ {slug}: arXiv:{aid} は実在するが原題との重なりが薄い\n"
                      f"    公式: {meta['title'][:90]}")
            else:
                print(f"✅ {slug}: arXiv:{aid} {meta['title'][:70]}")

    print(f"\n=== 出典 {checked}件を確認 / 実在しないもの {ng}件 ===")
    return 1 if ng else 0


if __name__ == "__main__":
    raise SystemExit(main())

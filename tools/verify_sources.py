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


def fetch_meta(arxiv_id: str, retries: int = 3) -> dict | None:
    """arXiv公式APIで論文の実在とタイトルを確認する。

    429（レート制限）は待って再試行する。2026-08-01 に全記事を検証したとき、
    確認できたのは45件だけで、残りはすべて 429 で落ちていた。
    このツールの結論は「実在しないもの 0件」だが、それは**確認できた分の
    うち0件**という意味でしかない。検証できていないものを検証済みと
    取り違えると、出典の裏取りという目的そのものが果たせない。
    """
    q = urllib.parse.urlencode({"id_list": arxiv_id, "max_results": 1})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(f"{API}?{q}", timeout=30) as r:
                root = ET.fromstring(r.read())
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < retries - 1:
                wait = 5 * (attempt + 1)     # 5秒 → 10秒
                print(f"    レート制限。{wait}秒待って再試行 ({arxiv_id})",
                      file=sys.stderr)
                time.sleep(wait)
                continue
            return {"error": f"HTTPError: {e.code}"}
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}
    else:
        return {"error": "レート制限が解けませんでした"}
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
    ok = 0
    unknown = 0
    for f in files:
        text = f.read_text(encoding="utf-8")
        ids = sorted(set(ID_RE.findall(text)))
        if not ids:
            continue
        slug = f.name.replace(".ja.md", "")
        for aid in ids:
            checked += 1
            meta = fetch_meta(aid)
            # arXiv API の案内は「3秒に1回」。0.4秒だと429が返り、
            # 2026-08-01 の実行では45件しか確認できなかった。
            time.sleep(3.0)
            if meta is None:
                print(f"❌ {slug}: arXiv:{aid} は実在しない", file=sys.stderr)
                ng += 1
                continue
            if "error" in meta:
                print(f"⚠️ {slug}: arXiv:{aid} 確認できず（{meta['error']}）")
                unknown += 1
                continue
            # 記事本文に原題が引用されていれば、単語の重なりで一致を見る。
            # 邦題だけの記事もあるため、原題が無いこと自体は不備にしない。
            words = norm(meta["title"])
            if len(words & norm(text)) < max(3, len(words) // 3):
                print(f"⚠️ {slug}: arXiv:{aid} は実在するが原題との重なりが薄い\n"
                      f"    公式: {meta['title'][:90]}")
            else:
                print(f"✅ {slug}: arXiv:{aid} {meta['title'][:70]}")
            ok += 1

    # 「確認できなかった分」を必ず出す。ここを黙って落とすと、
    # 未検証を検証済みと取り違える（2026-08-01 に実際そうなりかけた）。
    print(f"\n=== 出典 {checked}件 / 実在を確認 {ok}件 / "
          f"実在しない {ng}件 / 確認できず {unknown}件 ===")
    if unknown:
        print(f"⚠️ {unknown}件は未検証のまま。ネットワークかレート制限の"
              "影響なので、時間をおいて再実行してください。")
    return 1 if ng else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""ニュースの画像を配信元のOGP(og:image)から補完する。

RSSに画像が無い記事が多い(約9割)。各記事URLのHTMLから og:image のURLを
拾い、news.json の image に入れる。**画像はダウンロード・再配布しない**。
表示側はこのURLをそのまま <img src> で参照(ホットリンク)し、出典を明記する。
自サーバーへの転載はしないことで、著作権上の一線を守る。

収集(daily)の後に一度走らせる想定。取得できなかった記事は従来どおり
トピック別のイメージ写真(stock_image)でフォールバックする。
"""
import json
import re
import sys
import concurrent.futures
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.parse import urljoin

NEWS = Path(__file__).resolve().parent.parent / "data" / "news.json"
UA = "Mozilla/5.0 (compatible; AiOniBot/1.0; +https://ai-oni.com/about/)"

# og:image / twitter:image（属性の順序どちらでも拾えるよう2パターン）
_PATS = [
    re.compile(r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)(?::url)?["\'][^>]+content=["\']([^"\']+)["\']', re.I),
    re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)(?::url)?["\']', re.I),
]


def fetch_og_image(url: str) -> str | None:
    try:
        req = Request(url, headers={"User-Agent": UA})
        with urlopen(req, timeout=8) as r:
            raw = r.read(300_000)
        html = raw.decode("utf-8", "ignore")
        for pat in _PATS:
            m = pat.search(html)
            if m:
                img = m.group(1).strip()
                if img.startswith("//"):
                    img = "https:" + img
                elif img.startswith("/"):
                    img = urljoin(url, img)
                if img.startswith("http"):
                    return img
    except Exception:
        return None
    return None


# 1回で取りに行く件数の上限。
#
# 2026-08-01 時点で画像の無いニュースは2,300件を超える。上限なしで全件に
# HTTPリクエストを投げると数十分かかり、途中で打ち切られると最後の
# write_text に到達せず、取得できた分がまるごと消える。翌日も同じところから
# やり直すので、何度回しても増えない——翻訳と IndexNow で同じ壊れ方をしていた。
DEFAULT_LIMIT = 300
SAVE_EVERY = 50


def main() -> int:
    limit = DEFAULT_LIMIT
    for a in sys.argv[1:]:
        if a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])
    data = json.loads(NEWS.read_text(encoding="utf-8"))
    items = data.get("items", [])
    pending = [(i, it) for i, it in enumerate(items)
               if not it.get("image") and it.get("url")]
    # items は新しい順。先頭から処理すれば一覧に出る分から画像が付く。
    targets = pending[:limit] if limit else pending
    print(f"画像なし {len(pending)}件 → 今回 {len(targets)}件 / 全{len(items)}件",
          flush=True)
    if not targets:
        return 0

    def save() -> None:
        NEWS.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    got = done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(fetch_og_image, it["url"]): i for i, it in targets}
        for fut in concurrent.futures.as_completed(futs):
            i = futs[fut]
            img = fut.result()
            if img:
                items[i]["image"] = img
                got += 1
            done += 1
            # 途中で止まっても、そこまでの取得は残す。
            if done % SAVE_EVERY == 0:
                save()
                print(f"  …{done}/{len(targets)}件（取得 {got}）", flush=True)

    save()
    print(f"OGP画像を取得: {got}件 / 今回{len(targets)}件"
          f"（残り {len(pending) - len(targets)}件は次回）", flush=True)
    print(f"最終: image有り {sum(1 for x in items if x.get('image'))} / {len(items)}件", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""IndexNow — 検索エンジンにURL更新を直接通知する。

Bing / Yandex / Naver / Seznam が対応するオープンプロトコル。
**Webmaster Tools のアカウントもログインも不要**で、
サイトに鍵ファイルを置いておけば URL 一覧を POST するだけでよい。

ChatGPT のウェブ検索は Bing のインデックスを利用しているため、
ここへ通知しておくことは AI検索対策（AEO）としても効く。

仕組み:
  1. 任意の鍵（16進32文字）を決める
  2. https://<host>/<key>.txt に鍵と同じ文字列を置く
  3. api.indexnow.org に host / key / urlList を POST する
  4. 検索エンジンが鍵ファイルを取得して所有者確認し、URLを取り込む

実行:
    python3 -m aioni.indexnow          # sitemap の全URLを送信
    python3 -m aioni.indexnow --dry    # 送信せず内容だけ確認
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from . import config

# このサイト固有の鍵。static/<KEY>.txt として配信される。
# 変更したら鍵ファイルも作り直すこと（不一致だと検索エンジンに拒否される）。
KEY = "8f3c1d7a9b2e4c6d5e8f0a1b2c3d4e5f"

ENDPOINT = "https://api.indexnow.org/indexnow"
_SM_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def key_filename() -> str:
    return f"{KEY}.txt"


def sitemap_urls() -> list[str]:
    """生成済み sitemap.xml から URL を読み出す。"""
    path = config.DIST_DIR / "sitemap.xml"
    if not path.exists():
        return []
    root = ET.parse(path).getroot()
    return [
        loc.text.strip()
        for loc in root.iter(f"{_SM_NS}loc")
        if loc.text and loc.text.strip()
    ]


def submit(urls: list[str], host: str | None = None,
           scheme: str = "https") -> tuple[bool, str]:
    """URL一覧を IndexNow に送信する。(成功したか, メッセージ) を返す。"""
    host = host or config.SITE_DOMAIN
    if not urls:
        return False, "送信するURLがありません"
    # 1リクエストあたり最大10,000件
    urls = urls[:10000]
    payload = {
        "host": host,
        "key": KEY,
        "keyLocation": f"{scheme}://{host}/{key_filename()}",
        "urlList": urls,
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        ENDPOINT, data=data, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8",
                 "User-Agent": config.USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            code = resp.status
    except urllib.error.HTTPError as e:
        # 4xx でも意味のあるコードが返る
        body = e.read().decode("utf-8", "ignore")[:200]
        return False, f"HTTP {e.code}: {body or e.reason}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"

    # 200/202 が受理。422 は鍵の不一致など
    if code in (200, 202):
        return True, f"HTTP {code}: {len(urls)}件を受理"
    return False, f"HTTP {code}"


def main() -> int:
    urls = sitemap_urls()
    dry = "--dry" in sys.argv
    scheme = "http" if "--http" in sys.argv else "https"
    if scheme == "http":
        urls = [u.replace("https://", "http://") for u in urls]

    print(f"IndexNow: host={config.SITE_DOMAIN} key={KEY}")
    print(f"  鍵ファイル: {scheme}://{config.SITE_DOMAIN}/{key_filename()}")
    print(f"  送信対象: {len(urls)}件")
    if urls[:3]:
        for u in urls[:3]:
            print(f"    {u}")
        print("    ...")
    if dry:
        print("  (--dry のため送信しません)")
        return 0
    ok, msg = submit(urls, scheme=scheme)
    print(f"  結果: {'OK' if ok else 'NG'} — {msg}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

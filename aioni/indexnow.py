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
    python3 -m aioni.indexnow          # 前回から更新のあったURLだけ送信
    python3 -m aioni.indexnow --all    # sitemap の全URLを送信（鍵の変更直後など）
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


# 前回どのURLをどの更新日で送ったかの記録。差分だけ送るために使う。
_SENT_LOG = config.DATA_DIR / "indexnow_sent.json"


def sitemap_entries() -> dict[str, str]:
    """sitemap から {URL: lastmod} を読み出す。"""
    path = config.DIST_DIR / "sitemap.xml"
    if not path.exists():
        return {}
    root = ET.parse(path).getroot()
    out = {}
    for url in root.iter(f"{_SM_NS}url"):
        loc = url.findtext(f"{_SM_NS}loc")
        if loc and loc.strip():
            out[loc.strip()] = (url.findtext(f"{_SM_NS}lastmod") or "").strip()
    return out


def changed_urls(entries: dict[str, str]) -> tuple[list[str], dict]:
    """前回の送信から新しくなったURLだけを返す。

    IndexNow が求めているのは「追加・更新・削除されたURL」の通知で、
    サイト全URLの定期送信ではない。2026-08-01 まで毎回 sitemap の
    686件すべてを送っていた。毎日「全ページが変わった」と申告するのは
    sitemap の lastmod をビルド日で埋めていたのと同じ性質の誤りで、
    通知そのものが当てにされなくなる。

    lastmod は 2026-08-01 に実際の更新日を出すよう直したので、
    前回送った値と突き合わせれば「本当に変わったURL」が分かる。
    記録が無い初回は全件を返す（それは正しい通知）。
    """
    try:
        prev = json.loads(_SENT_LOG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        prev = {}
    if not prev:
        return list(entries), entries
    changed = [u for u, lm in entries.items() if prev.get(u) != lm]
    return changed, entries


def record_sent(entries: dict[str, str]) -> None:
    """送信できたURLと更新日を残す。次回はこことの差分だけ送る。"""
    try:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _SENT_LOG.write_text(json.dumps(entries, ensure_ascii=False, indent=0),
                             encoding="utf-8")
    except OSError as e:
        print(f"  ⚠️ 送信記録を保存できませんでした: {e}", file=sys.stderr)


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
    dry = "--dry" in sys.argv
    scheme = "http" if "--http" in sys.argv else "https"
    entries = sitemap_entries()

    # 既定は差分だけ。--all で全件送る（鍵を変えた直後などに使う）。
    if "--all" in sys.argv:
        urls, reason = list(entries), "全件（--all 指定）"
    else:
        urls, entries = changed_urls(entries)
        reason = "前回から更新のあったURLのみ"

    if scheme == "http":
        urls = [u.replace("https://", "http://") for u in urls]

    print(f"IndexNow: host={config.SITE_DOMAIN} key={KEY}")
    print(f"  鍵ファイル: {scheme}://{config.SITE_DOMAIN}/{key_filename()}")
    print(f"  送信対象: {len(urls)}件 / sitemap {len(entries)}件（{reason}）")
    if not urls:
        print("  更新なし。送信しません。")
        return 0
    for u in urls[:3]:
        print(f"    {u}")
    if len(urls) > 3:
        print("    ...")
    if dry:
        print("  (--dry のため送信しません)")
        return 0
    ok, msg = submit(urls, scheme=scheme)
    print(f"  結果: {'OK' if ok else 'NG'} — {msg}")
    if ok:
        record_sent(entries)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

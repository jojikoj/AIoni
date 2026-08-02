#!/usr/bin/env python3
"""AEO施策の「拾われ方」を Search Console で実測する。

2系統:
  A. ページ別パフォーマンス（news/check 配下）… siteFullUser で動く。
     表示回数・クリック・CTR・平均掲載順位を出す。数日〜数週間データが溜まってから有効。
  B. リッチリザルト検出（URL Inspection API, --inspect）… ⚠ siteOwner 権限が必須。
     現在の認証IDは siteFullUser のため 403。SCで対象アカウントを「所有者」に追加し
     gcloud auth application-default login を取り直せば動く。

前提: gcloud ADC（webmasters.readonly）。python3.12 で実行（google-api-python-client 入り）。
使い方:
  python3.12 tools/inspect_richresults.py            # ページ別パフォーマンス
  python3.12 tools/inspect_richresults.py --inspect  # URL Inspection も試行（owner権限が要る）
"""
from __future__ import annotations

import sys
from datetime import date, timedelta

import google.auth
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
SITE = "sc-domain:ai-oni.com"

INSPECT_URLS = [
    "https://ai-oni.com/news/zenn_ai-7bee31500e/",
    "https://ai-oni.com/check/",
]


def perf_by_page(sc, contains: str, days: int = 28, limit: int = 15):
    end = date.today() - timedelta(days=3)
    start = end - timedelta(days=days)
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["page"],
        "dimensionFilterGroups": [{"filters": [
            {"dimension": "page", "operator": "contains", "expression": contains}]}],
        "rowLimit": limit,
    }
    return sc.searchanalytics().query(siteUrl=SITE, body=body).execute().get("rows", [])


def main() -> int:
    do_inspect = "--inspect" in sys.argv
    try:
        creds, _ = google.auth.default(scopes=SCOPES)
        sc = build("searchconsole", "v1", credentials=creds, cache_discovery=False)
    except Exception as e:
        print(f"認証に失敗: {e}", file=sys.stderr)
        return 2

    print(f"# AEO 拾われ方 実測 — {SITE}\n")
    for label, needle in [("ニュース(/news/)", "/news/"), ("チェッカー(/check/)", "/check/")]:
        rows = perf_by_page(sc, needle)
        print(f"## {label}")
        if not rows:
            print("  データなし（クロール・蓄積前。数日〜数週間おいて再実行）\n")
            continue
        for r in rows:
            url = r["keys"][0]
            print(f"  表示{r.get('impressions', 0):>5.0f} クリック{r.get('clicks', 0):>3.0f} "
                  f"CTR{r.get('ctr', 0) * 100:4.1f}% 順位{r.get('position', 0):4.1f}  {url}")
        print()

    if do_inspect:
        print("## リッチリザルト検出（URL Inspection）")
        for url in INSPECT_URLS:
            try:
                res = sc.urlInspection().index().inspect(
                    body={"inspectionUrl": url, "siteUrl": SITE}).execute()
                rich = res.get("inspectionResult", {}).get("richResultsResult", {})
                items = rich.get("detectedItems", [])
                detail = ", ".join(f"{i.get('richResultType', '?')}x{len(i.get('items', []))}"
                                   for i in items) or "未検出"
                print(f"  {url} -> {detail}")
            except Exception as e:
                msg = str(e)
                if "permission" in msg or "own this site" in msg:
                    print(f"  {url} -> owner権限が必要（現在 siteFullUser）")
                else:
                    print(f"  {url} -> 失敗: {msg[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

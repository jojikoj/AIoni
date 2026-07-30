"""Search Console の状態を API で取得してレポートする（ブラウザ不要・cron用）。

なぜ API か:
  サイトマップの取得状況や検索キーワードの確認を、ログイン済みブラウザ
  （Playwright）でやると Google のセッション切れ・プロファイルのロックで
  頻繁にコケる。API なら認証トークン1つで無人実行でき、cron に載せられる。

認証:
  gcloud の ADC（アプリケーションデフォルト認証）を使う。事前に一度だけ
  次を実行して webmasters スコープ付きのトークンを作っておくこと:

    gcloud auth application-default login \
      --scopes=https://www.googleapis.com/auth/webmasters.readonly,https://www.googleapis.com/auth/cloud-platform

  以降は refresh token が自動更新されるため、再ログインは不要
  （トークンを revoke するか半年放置しない限り）。

やること:
  1. サイトマップ sc-domain:ai-oni.com/sitemap.xml の状態を取得
     （最終取得日時・保留中か・エラー/警告・検出URL数）
  2. 直近7日の検索クエリ上位を取得（表示回数・クリック）
  3. 標準出力にサマリを出し、日付つきレポートを reports/ に保存

実行:
    python3 tools/searchconsole_report.py                 # sc-domain:ai-oni.com
    python3 tools/searchconsole_report.py sc-domain:example.com
"""
from __future__ import annotations

import os
import pathlib
import sys
from datetime import date, timedelta

import google.auth
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
GA4_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]
ROOT = pathlib.Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"

# GA4 プロパティID（数字）。空のあいだは GA4 セクションを出力しない。
# 測定ID(G-SNQPGVMWWW)ではなくプロパティIDを入れること。
# GA4管理画面 → 管理 → プロパティの詳細 → 「プロパティID」
GA4_PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID", "")

# GA4 を読むには ADC に analytics.readonly スコープが必要。
# 一度だけ次を実行する（Search Console のスコープも同時に付け直す）:
#   gcloud auth application-default login \
#     --scopes=https://www.googleapis.com/auth/webmasters.readonly,\
# https://www.googleapis.com/auth/analytics.readonly,\
# https://www.googleapis.com/auth/cloud-platform
GA4_SCOPE_HINT = (
    "gcloud auth application-default login --scopes="
    "https://www.googleapis.com/auth/webmasters.readonly,"
    "https://www.googleapis.com/auth/analytics.readonly,"
    "https://www.googleapis.com/auth/cloud-platform"
)


def service():
    creds, _ = google.auth.default(scopes=SCOPES)
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def ga4_section(days: int = 28) -> list[str]:
    """GA4 の流入元・回遊・問い合わせ到達を読む。

    Search Console は「検索でどう見えたか」までしか分からない。
    サイトに来たあとどう動いたか（流入元・直帰・/contact/ 到達）は
    GA4 にしかない。スコープ未付与のあいだは手順を出して先に進む。
    """
    if not GA4_PROPERTY_ID:
        return ["- GA4_PROPERTY_ID が未設定のためスキップ",
                "  （GA4管理画面 → 管理 → プロパティの詳細 → プロパティID を "
                "環境変数 GA4_PROPERTY_ID に入れる）"]
    try:
        creds, _ = google.auth.default(scopes=GA4_SCOPES)
        ga = build("analyticsdata", "v1beta", credentials=creds,
                   cache_discovery=False)
        body = {
            "dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "today"}],
            "dimensions": [{"name": "sessionDefaultChannelGroup"}],
            "metrics": [{"name": "sessions"}, {"name": "activeUsers"},
                        {"name": "engagementRate"}],
            "limit": 20,
        }
        res = ga.properties().runReport(
            property=f"properties/{GA4_PROPERTY_ID}", body=body).execute()
        lines = [f"### 流入チャネル別（直近{days}日）"]
        for r in res.get("rows", []):
            ch = r["dimensionValues"][0]["value"]
            s, u, e = (v["value"] for v in r["metricValues"])
            lines.append(f"- {ch} … セッション {s} / ユーザー {u} / "
                         f"エンゲージメント率 {float(e) * 100:.1f}%")
        if len(lines) == 1:
            lines.append("- データがありません")

        # 問い合わせページへの到達。ここが0なら記事がいくら読まれても受注はゼロ。
        body2 = {
            "dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "today"}],
            "dimensions": [{"name": "pagePath"}],
            "metrics": [{"name": "screenPageViews"}, {"name": "activeUsers"}],
            "orderBys": [{"metric": {"metricName": "screenPageViews"},
                          "desc": True}],
            "limit": 15,
        }
        res2 = ga.properties().runReport(
            property=f"properties/{GA4_PROPERTY_ID}", body=body2).execute()
        lines.append("")
        lines.append(f"### ページ別 上位（直近{days}日）")
        for r in res2.get("rows", []):
            path = r["dimensionValues"][0]["value"]
            pv, u = (v["value"] for v in r["metricValues"])
            mark = " ← 収益導線" if path.startswith("/contact") else ""
            lines.append(f"- {path} … PV {pv} / ユーザー {u}{mark}")
        return lines
    except Exception as e:
        msg = str(e)
        if "ACCESS_TOKEN_SCOPE_INSUFFICIENT" in msg or "insufficient" in msg:
            return ["- GA4 を読む権限がありません（ADC のスコープ不足）。",
                    "  一度だけ次を実行してください:",
                    f"  `{GA4_SCOPE_HINT}`"]
        return [f"- 取得失敗: {msg[:300]}"]


def sitemap_status(sc, site: str) -> list[dict]:
    """送信済みサイトマップの状態を返す。"""
    res = sc.sitemaps().list(siteUrl=site).execute()
    out = []
    for s in res.get("sitemap", []):
        contents = s.get("contents", [{}])
        out.append({
            "path": s.get("path", ""),
            "lastDownloaded": s.get("lastDownloaded", "(未取得)"),
            "isPending": s.get("isPending", False),
            "isSitemapsIndex": s.get("isSitemapsIndex", False),
            "warnings": s.get("warnings", "0"),
            "errors": s.get("errors", "0"),
            "submitted": contents[0].get("submitted", "?") if contents else "?",
            "indexed": contents[0].get("indexed", "?") if contents else "?",
        })
    return out


def top_queries(sc, site: str, days: int = 7, limit: int = 20) -> list[dict]:
    """直近 days 日の検索クエリ上位を返す。"""
    end = date.today() - timedelta(days=3)      # SC は2〜3日遅延するため終端を下げる
    start = end - timedelta(days=days)
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "dimensions": ["query"],
        "rowLimit": limit,
    }
    res = sc.searchanalytics().query(siteUrl=site, body=body).execute()
    return res.get("rows", [])


def main() -> int:
    site = sys.argv[1] if len(sys.argv) > 1 else "sc-domain:ai-oni.com"
    try:
        sc = service()
    except Exception as e:
        print(f"❌ 認証に失敗しました: {e}\n"
              f"   先に次を一度だけ実行してください:\n"
              f"   gcloud auth application-default login "
              f"--scopes=https://www.googleapis.com/auth/webmasters.readonly,"
              f"https://www.googleapis.com/auth/cloud-platform",
              file=sys.stderr)
        return 2

    lines: list[str] = [f"# Search Console レポート — {site}", ""]

    lines.append("## サイトマップ")
    try:
        maps = sitemap_status(sc, site)
        if not maps:
            lines.append("- 送信済みサイトマップがありません")
        for m in maps:
            state = "取得待ち" if m["isPending"] else "取得済み"
            lines.append(
                f"- `{m['path']}` … {state} / 最終取得 {m['lastDownloaded']} / "
                f"エラー {m['errors']} 警告 {m['warnings']} / "
                f"送信URL {m['submitted']} 検出 {m['indexed']}"
            )
    except Exception as e:
        lines.append(f"- 取得失敗: {e}")

    lines.append("")
    lines.append("## 検索クエリ上位（直近7日・2〜3日遅延あり）")
    try:
        rows = top_queries(sc, site)
        if not rows:
            lines.append("- まだデータがありません（公開直後は数日かかります）")
        for r in rows:
            q = r["keys"][0]
            lines.append(
                f"- {q} … 表示 {int(r.get('impressions',0))} / "
                f"クリック {int(r.get('clicks',0))} / "
                f"CTR {r.get('ctr',0)*100:.1f}% / 掲載順位 {r.get('position',0):.1f}"
            )
    except Exception as e:
        lines.append(f"- 取得失敗: {e}")

    # GA4（サイトに来たあとの動き）。ai-oni.com 以外を指定したときは出さない。
    if site.endswith("ai-oni.com"):
        lines.append("")
        lines.append("## GA4（流入元・回遊・問い合わせ到達）")
        lines.extend(ga4_section())

    report = "\n".join(lines)
    print(report)

    REPORTS.mkdir(exist_ok=True)
    # サイト名をファイル名に含める。含めないと同日に別サイト（uchuchu 等）を
    # 実行したときに ai-oni のレポートを上書きしてしまう（2026-07-29 に実際に発生）。
    slug = site.replace("sc-domain:", "").replace("https://", "").strip("/").replace("/", "_")
    out = REPORTS / f"searchconsole_{slug}_{date.today().isoformat()}.md"
    out.write_text(report + "\n", encoding="utf-8")
    print(f"\n→ 保存: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

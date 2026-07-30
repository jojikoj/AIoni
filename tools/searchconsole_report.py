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

# GA4 プロパティID（数字）。空なら accountSummaries から自動で探す。
# 測定ID(G-SNQPGVMWWW)ではなくプロパティIDを入れること。
GA4_PROPERTY_ID = os.environ.get("GA4_PROPERTY_ID", "")

# GA4はサービスアカウントで読む。
#
# なぜ ADC ではないのか（2026-07-30）:
#   gcloud の既定クライアントIDでは analytics.readonly が Google 側で
#   ブロックされており、`gcloud auth application-default login
#   --scopes=...analytics.readonly` は同意画面で拒否される。
#   （gcloud自身が「blocked soon for the default client ID」と警告する）
#   サービスアカウントなら同意画面を通らず、無人cronにも向く。
#
# 準備（一度だけ）:
#   1. 鍵は tools/ が作成済み → ~/.config/aioni-ga4-sa.json
#   2. GA4管理画面 → 管理 → プロパティのアクセス管理 → ＋ →
#      下記のメールアドレスを「閲覧者」で追加
GA4_SA_KEY = pathlib.Path(
    os.environ.get("GA4_SA_KEY", pathlib.Path.home() / ".config" / "aioni-ga4-sa.json"))
GA4_SA_EMAIL = "aioni-ga4-reader@a-form-prod.iam.gserviceaccount.com"


def service():
    creds, _ = google.auth.default(scopes=SCOPES)
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


def _ga4_creds():
    """GA4用の資格情報。サービスアカウント鍵があればそれを使う。"""
    if GA4_SA_KEY.exists():
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_file(
            str(GA4_SA_KEY), scopes=GA4_SCOPES)
    # 鍵が無ければ ADC を試す（スコープが付いていれば動く）
    creds, _ = google.auth.default(scopes=GA4_SCOPES)
    return creds


def ga4_property_id(creds) -> str:
    """プロパティIDを自動で見つける。環境変数があればそれを優先。"""
    if GA4_PROPERTY_ID:
        return GA4_PROPERTY_ID
    admin = build("analyticsadmin", "v1beta", credentials=creds,
                  cache_discovery=False)
    res = admin.accountSummaries().list().execute()
    for acc in res.get("accountSummaries", []):
        for p in acc.get("propertySummaries", []):
            # 「AIの鬼」「AIoni」「ai-oni」を含むプロパティを優先
            name = (p.get("displayName") or "").lower()
            if any(k in name for k in ("鬼", "aioni", "ai-oni", "ai oni")):
                return p["property"].split("/")[-1]
    # 見つからなければ最初のプロパティ
    for acc in res.get("accountSummaries", []):
        for p in acc.get("propertySummaries", []):
            return p["property"].split("/")[-1]
    return ""


def ga4_section(days: int = 28) -> list[str]:
    """GA4 の流入元・回遊・問い合わせ到達を読む。

    Search Console は「検索でどう見えたか」までしか分からない。
    サイトに来たあとどう動いたか（流入元・直帰・/contact/ 到達）は
    GA4 にしかない。スコープ未付与のあいだは手順を出して先に進む。
    """
    try:
        creds = _ga4_creds()
        prop = ga4_property_id(creds)
        if not prop:
            return ["- GA4のプロパティが見つかりません。",
                    f"  GA4管理画面 → 管理 → プロパティのアクセス管理 で "
                    f"`{GA4_SA_EMAIL}` を「閲覧者」で追加してください。"]
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
            property=f"properties/{prop}", body=body).execute()
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
            property=f"properties/{prop}", body=body2).execute()
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
        if ("PERMISSION_DENIED" in msg or "insufficient" in msg
                or "does not have sufficient" in msg or "403" in msg):
            return ["- GA4 を読む権限がありません。",
                    "  GA4管理画面 → 管理 → プロパティのアクセス管理 → ＋ で",
                    f"  `{GA4_SA_EMAIL}` を「閲覧者」として追加してください。"]
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

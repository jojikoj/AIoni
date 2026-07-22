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

import pathlib
import sys
from datetime import date, timedelta

import google.auth
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]
ROOT = pathlib.Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"


def service():
    creds, _ = google.auth.default(scopes=SCOPES)
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


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

    report = "\n".join(lines)
    print(report)

    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / f"searchconsole_{date.today().isoformat()}.md"
    out.write_text(report + "\n", encoding="utf-8")
    print(f"\n→ 保存: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

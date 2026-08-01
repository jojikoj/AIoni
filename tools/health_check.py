"""公開中のサイトが本当に更新されているかを、外から見て確かめる。

## なぜ要るか

2026-08-01 に気づいた事故：本番の最新ニュースが 7-29 で止まっており、
3日間まったく更新されていなかった。「1日2回集約する」と掲げている
サイトが3日止まっても、誰も気づいていなかった。

止まった原因は実行機（Mac mini）側にあったが、問題はそこではない。
**止まったことに気づく手段が無かった** ことが問題。日次処理のログも、
それを見守る watchdog のログも、同じ機械の上にある。その機械ごと
止まれば、ログも watchdog も一緒に黙るので、何も起きていないのと
区別がつかない。

だからこの点検は、実行機の中を見ない。**公開されている HTML を
外から取得して、載っている日付だけを見る。** 誰がどこで動かしても
同じ答えが出るし、実行機が丸ごと止まっていても正しく「止まっている」
と言える。

## 使い方

    python3 tools/health_check.py          # 判定して表示（正常なら終了コード0）
    python3 tools/health_check.py --notify  # 異常時に macOS の通知も出す

cron に載せるなら1日2回で足りる（更新は1日2回のため）:

    0 11,20 * * * /usr/bin/python3 <ここ>/health_check.py --notify >> <log> 2>&1
"""
from __future__ import annotations

import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone

SITE = "https://ai-oni.com"
# 1日2回更新なので、丸1日以上あいたら異常。半端に短くすると、
# 収集が1回空振りしただけで鳴って、狼少年になる。
STALE_HOURS = 30
UA = "Mozilla/5.0 (compatible; AIoni health check)"


def fetch(path: str) -> str:
    req = urllib.request.Request(SITE + path, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def latest_news_time() -> datetime | None:
    """ニュース一覧に出ている最新の日時。サイトが実際に出しているものを読む。"""
    html = fetch("/news/")
    stamps = re.findall(r'<time[^>]*datetime="([^"]+)"', html)
    times = []
    for s in stamps:
        try:
            times.append(datetime.fromisoformat(s.replace("Z", "+00:00")))
        except ValueError:
            continue
    return max(times) if times else None


def notify(title: str, message: str) -> None:
    """macOS の通知センターに出す。失敗しても点検自体は続ける。"""
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification {message!r} with title {title!r}'],
            check=False, capture_output=True, timeout=10)
    except Exception:
        pass


def main() -> int:
    do_notify = "--notify" in sys.argv
    now = datetime.now(timezone.utc)
    stamp = now.astimezone().strftime("%F %H:%M")

    try:
        latest = latest_news_time()
    except Exception as e:
        msg = f"サイトを取得できません: {e}"
        print(f"[{stamp}] ❌ {msg}")
        if do_notify:
            notify("AIの鬼 点検", msg)
        return 2

    if latest is None:
        msg = "ニュース一覧に日付が1件も見つかりません"
        print(f"[{stamp}] ❌ {msg}")
        if do_notify:
            notify("AIの鬼 点検", msg)
        return 2

    hours = (now - latest).total_seconds() / 3600
    local = latest.astimezone().strftime("%F %H:%M")
    if hours > STALE_HOURS:
        msg = (f"更新が {hours:.0f} 時間止まっています"
               f"（最新のニュースは {local}）")
        print(f"[{stamp}] ⚠️ {msg}")
        print("    実行機の日次処理が動いているか確認してください。")
        if do_notify:
            notify("AIの鬼 更新が止まっています", msg)
        return 1

    print(f"[{stamp}] ✅ 正常（最新のニュースは {local} / {hours:.1f} 時間前）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

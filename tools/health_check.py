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


# 公開サイトに載っているべき目印。
#
# 2026-08-01、実行機が main を取り込まないまま日次を回し、その日の改修が
# 公開サイトから丸ごと消えた。ページは正常に開き、日付も新しいので、
# 鮮度の点検だけでは気づけない。「入っているはずの物が入っているか」を
# 別に見る必要がある。
#
# ここに並べるのは「消えたら困る、かつ HTML から一目で分かる」ものだけ。
# 増やしすぎると、体裁を変えただけで鳴るようになる。
EXPECTED = [
    ("/articles/ai-cost-structure/", "cta-banner", "記事末の相談バナー"),
    ("/articles/ai-cost-structure/", "article-related", "関連記事欄"),
    ("/articles/ai-cost-structure/", 'media="print"', "フォントの非同期読み込み"),
]


def check_expected() -> list[str]:
    """公開サイトから消えている目印を返す。全部あれば空。"""
    missing = []
    cache: dict[str, str] = {}
    for path, needle, label in EXPECTED:
        try:
            if path not in cache:
                cache[path] = fetch(path)
            if needle not in cache[path]:
                missing.append(label)
        except Exception as e:
            missing.append(f"{label}（確認できず: {e}）")
    return missing


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

    missing = check_expected()
    if missing:
        msg = "公開サイトから消えている要素: " + " / ".join(missing)
        print(f"[{stamp}] ⚠️ {msg}")
        print("    古いコードを持つ機械が公開を上書きした可能性があります。")
        print("    その機械で git pull してから、もう一度公開してください。")
        if do_notify:
            notify("AIの鬼 公開内容が巻き戻っています", msg)
        return 1

    print(f"[{stamp}] ✅ 正常（最新のニュースは {local} / {hours:.1f} 時間前 "
          f"/ 目印 {len(EXPECTED)} 件すべて確認）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

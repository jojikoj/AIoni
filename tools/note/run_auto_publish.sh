#!/bin/bash
# note自動公開を cron から回すラッパー。平日1本、下書きを公開する。
# crontab: 30 7 * * 1-5  → 平日07:30
set -uo pipefail
cd "$(dirname "$0")"

export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.local/bin:$PATH"
export HOME="${HOME:-/Users/kojimajouji}"

LOG="$(dirname "$0")/auto_publish.log"

echo "===== $(date '+%Y-%m-%d %H:%M:%S') 開始 =====" >> "$LOG"

# 1) 下書きを1本公開する
node auto_publish.mjs >> "$LOG" 2>&1
pub=$?

# 2) 在庫を目標まで補充する（在庫が足りていれば何もしない）
#    執筆は claude sonnet を単発で呼ぶ。品質ゲートを通ったものだけ下書きに積む。
echo "----- 補充チェック -----" >> "$LOG"
node refill.mjs >> "$LOG" 2>&1
ref=$?

echo "----- 公開:$pub 補充:$ref -----" >> "$LOG"
exit $pub

#!/usr/bin/env bash
# 7時間後の単発再開用ラッパー（launchd から呼ばれる）。
# body_long の未生成分を続きから生成し、終わったら自分自身(LaunchAgent)を撤去する。
set -uo pipefail

export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export AIONI_CLAUDE_BIN="/Users/kojimajouji/.local/bin/claude"

cd "$HOME/AIoni" || exit 1
LOG="$HOME/AIoni/data/gen_resume.log"
PLIST="$HOME/Library/LaunchAgents/com.aioni.resumegen.plist"

echo "=== resume $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$LOG"
# 既に手動生成が走っている場合は並走(news.json同時書き込み)を避けて撤収
if pgrep -f gen_news_summaries.py >/dev/null; then
    echo "既に生成プロセスが実行中のためスキップ" >> "$LOG"
    /bin/launchctl unload "$PLIST" 2>/dev/null
    rm -f "$PLIST"
    exit 0
fi
# アイドルスリープを抑えつつ未生成分を生成（逐次保存・連続失敗で自動中断）
/usr/bin/caffeinate -i /usr/bin/python3 tools/gen_news_summaries.py >> "$LOG" 2>&1
echo "=== done $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$LOG"

# 単発化: 実行後は自分を撤去して二度と発火させない
/bin/launchctl unload "$PLIST" 2>/dev/null
rm -f "$PLIST"

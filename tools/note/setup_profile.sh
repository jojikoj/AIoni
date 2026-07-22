#!/bin/bash
# note自動公開が使うログイン専用プロファイルを用意する。
# MCP用プロファイル(~/.claude/playwright-mcp-profile)のログインcookieを複製する。
# noteのログインが切れたとき（自動公開が urlname 不一致で失敗したとき）に再実行する。
#
#   bash setup_profile.sh
#
# 前提: 対話セッションで note.com に jojinja でログイン済みであること。
set -euo pipefail

SRC="$HOME/.claude/playwright-mcp-profile"
DST="$(cd "$(dirname "$0")" && pwd)/.chrome-profile"

[ -d "$SRC" ] || { echo "元プロファイルが無い: $SRC"; exit 1; }

echo "複製中: $SRC → $DST"
rm -rf "$DST"
cp -R "$SRC" "$DST"

# ロック/シングルトン系を除去（残っていると起動できない）
find "$DST" -maxdepth 2 \( -name "Singleton*" -o -name "*.lock" -o -name "lockfile" \) -delete 2>/dev/null || true

echo "完了。node auto_publish.mjs --dry-run で確認してください。"

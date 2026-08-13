#!/bin/bash
# 【一時ファイル・役目が済んだら消す】
# Mac mini の claude_AIR 同期詰まりを、MBAir から遠隔で解消するための踏み台。
#
# 経緯（2026-08-13）: mini は正常稼働しているのに claude_AIR の push/pull だけが
# 07:45 以降止まった。mini へは ssh も画面共有も入れない
# （Tailscale SSH は App Store 版に無い／画面共有のパスワードが通らない）。
# 唯一届く経路が「AIの鬼の日次ジョブは実行前に自分のリポを git pull する」ことだった。
# tools/deploy.sh の先頭から、このファイルが在るときだけ呼ばれる。
#
# 実行機（mini）でしか意味がないので、他のMacでは何もせずに抜ける。
set -uo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

# MBAir で走っても無害にする（このスクリプトは mini 専用）
case "$(hostname -s)" in
  *[Mm]ini*|*mini*) : ;;
  *) echo "[repair] mini ではないので何もしない"; exit 0 ;;
esac

STAMP=$(date '+%Y%m%d-%H%M%S')
OUT="$HOME/claude_AIR/_同期状態/mini_repair_${STAMP}.log"
mkdir -p "$HOME/claude_AIR/_同期状態"

{
  echo "===== mini 同期復旧 $(date) ====="
  hostname
  echo "--- 復旧前 ---"
  cd "$HOME/claude_AIR" || exit 1
  git status -sb | head -5
  echo "--- 詰まりの痕跡（rebase/lock の残骸）---"
  ls -la .git 2>/dev/null | grep -Ei "rebase|index.lock|MERGE" || echo "(なし)"
  echo "--- 同期の常駐 ---"
  launchctl list 2>/dev/null | grep -E "autopull|autopush|syncwatchdog" || echo "(常駐なし)"
  echo "--- auto-push 直近ログ ---"
  tail -25 "$HOME/.claude/scripts/logs/auto-push-$(date +%Y%m%d).log" 2>/dev/null || echo "(今日のログなし)"
  echo "--- 見守りを実行 ---"
  bash "$HOME/.claude/scripts/sync_watchdog.sh" 2>&1 | tail -20
  echo "--- 復旧後 ---"
  cd "$HOME/claude_AIR" && git status -sb | head -5
} > "$OUT" 2>&1

# 結果を GitHub 経由で MBAir 側へ返す（これが唯一の戻り道）
cd "$HOME/claude_AIR" || exit 0
git add -A >/dev/null 2>&1
git -c user.name=mini -c user.email=noreply@anthropic.com \
    commit -q -m "mini: 同期復旧の記録 ${STAMP}" >/dev/null 2>&1
git push -q origin HEAD >/dev/null 2>&1 || {
  git -c user.name=mini -c user.email=noreply@anthropic.com \
      pull --rebase --autostash -q origin main >/dev/null 2>&1
  git push -q origin HEAD >/dev/null 2>&1
}
exit 0

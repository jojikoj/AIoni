#!/bin/bash
# 【一時ファイル・役目が済んだら消す】
# Mac mini の claude_AIR 同期詰まりを、MBAir から遠隔で解消するための踏み台。
#
# 経緯（2026-08-13）: mini は正常稼働しているのに claude_AIR の push/pull だけが
# 07:45 以降止まった（同時刻に note自動投稿ジョブがタイムアウトで強制終了されており、
# .git/index.lock の置き土産が濃厚）。mini へは ssh も画面共有も入れないため、
# 「日次ジョブが実行前に自分のリポを git pull する」性質だけが唯一の経路。
# tools/deploy.sh の先頭から、このファイルが在るときだけ呼ばれる。
#
# 戻り道は claude_AIR ではなく AIoni リポに置く。
# claude_AIR が壊れている前提なので、そこへ書いても外に出られない（初回の失敗理由）。
set -uo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

STAMP=$(date '+%Y%m%d-%H%M%S')
OUT="$HOME/AIoni/reports/mini_repair_${STAMP}.log"
mkdir -p "$HOME/AIoni/reports"

{
  echo "===== 同期復旧の記録 $(date) ====="
  echo "hostname      : $(hostname 2>/dev/null)"
  echo "hostname -s   : $(hostname -s 2>/dev/null)"
  echo "ComputerName  : $(scutil --get ComputerName 2>/dev/null)"

  if [ ! -d "$HOME/claude_AIR/.git" ]; then
    echo "claude_AIR が無いので何もしない"; exit 0
  fi
  case "$(hostname -s 2>/dev/null)" in
    *MBAir*|*mbair*) echo "MBAir 上なので復旧はしない（無害に終了）"; exit 0 ;;
  esac

  echo "--- 復旧前 ---"
  cd "$HOME/claude_AIR" || exit 1
  git status -sb 2>&1 | head -5
  echo "--- 詰まりの痕跡（rebase/lock の残骸）---"
  ls -la .git 2>/dev/null | grep -Ei "rebase|index.lock|MERGE" || echo "(なし)"
  echo "--- 同期の常駐 ---"
  launchctl list 2>/dev/null | grep -E "autopull|autopush|syncwatchdog" || echo "(常駐なし)"
  echo "--- auto-push 直近ログ ---"
  tail -30 "$HOME/.claude/scripts/logs/auto-push-$(date +%Y%m%d).log" 2>/dev/null || echo "(今日のログなし)"
  echo "--- 見守りを実行 ---"
  bash "$HOME/.claude/scripts/sync_watchdog.sh" 2>&1 | tail -25
  echo "--- 復旧後 ---"
  cd "$HOME/claude_AIR" && git status -sb 2>&1 | head -5
  echo "--- 共通フレームは届いたか（今夜の日次はこれが要る）---"
  ls -l "$HOME/claude_AIR/TOEcompany/メディア事業部/共通/運用/media-daily.sh" 2>&1
} > "$OUT" 2>&1

# 戻り道: AIoni リポに載せて push する（このリポの同期は生きている）
cd "$HOME/AIoni" || exit 0
git add "reports/mini_repair_${STAMP}.log" >/dev/null 2>&1
git -c user.name=mini -c user.email=noreply@anthropic.com \
    commit -q -m "mini: 同期復旧の記録 ${STAMP}" >/dev/null 2>&1
git push -q origin HEAD >/dev/null 2>&1 || {
  git -c user.name=mini -c user.email=noreply@anthropic.com \
      pull --rebase --autostash -q origin main >/dev/null 2>&1
  git push -q origin HEAD >/dev/null 2>&1
}
exit 0

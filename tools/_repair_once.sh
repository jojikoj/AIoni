#!/bin/bash
# 【一時ファイル・役目が済んだら消す】
# Mac mini の claude_AIR を detached HEAD から main へ戻し、同期の常駐を入れる。
#
# 2026-08-13 の状況: mini の claude_AIR が detached HEAD のまま固定され、
# 追跡先を失って pull/push が両方効かなくなっていた（同期失敗285件）。
# 07:45 に note自動投稿ジョブがタイムアウトで強制終了された際、
# 進行中だった rebase が .git/index.lock を抱えたまま殺され、
# 「戻れないまま」detached で残ったのが発端と見られる。
# mini へは ssh も画面共有も入れないため、日次ジョブが実行前に自分のリポを
# git pull する性質を使い、tools/deploy.sh の先頭からこれを呼んでいる。
#
# 方針: 消さない・捨てない。未コミットは必ず先に退避コミットしてから main へ戻す。
set -uo pipefail
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

STAMP=$(date '+%Y%m%d-%H%M%S')
OUT="$HOME/AIoni/reports/mini_repair_${STAMP}.log"
mkdir -p "$HOME/AIoni/reports"
R="$HOME/claude_AIR"
G="git -c user.name=mini -c user.email=noreply@anthropic.com"

{
  echo "===== claude_AIR 復旧 $(date) ====="
  echo "host: $(hostname -s 2>/dev/null) / $(scutil --get ComputerName 2>/dev/null)"
  [ -d "$R/.git" ] || { echo "claude_AIR が無い"; exit 0; }
  case "$(hostname -s 2>/dev/null)" in
    *MBAir*|*mbair*) echo "MBAir 上なので何もしない"; exit 0 ;;
  esac
  cd "$R" || exit 1

  echo "--- 復旧前 ---"
  git status -sb 2>&1 | head -3
  git log -1 --format='HEAD=%h %ci %s' 2>&1

  echo "--- 1. 残留ロックと中断rebaseの掃除 ---"
  rm -f .git/index.lock 2>/dev/null && echo "index.lock を除去" || echo "index.lock なし"
  if [ -e .git/rebase-merge ] || [ -e .git/rebase-apply ]; then
    git rebase --abort 2>&1 && echo "中断rebase を abort"
  else
    echo "中断rebase なし"
  fi

  echo "--- 2. 未コミットを退避コミット（捨てない）---"
  if [ -n "$(git status --porcelain)" ]; then
    git add -A 2>&1 | tail -1
    $G commit -q -m "mini: 復旧前の退避コミット ${STAMP}" 2>&1 | tail -2
    echo "退避した: $(git log -1 --format='%h %s')"
  else
    echo "未コミットなし"
  fi

  echo "--- 3. detached なら退避ブランチに固定してから main へ ---"
  if ! git symbolic-ref -q HEAD >/dev/null 2>&1; then
    git branch "rescue-mini-${STAMP}" 2>&1 | tail -1
    echo "退避ブランチ rescue-mini-${STAMP} を作成（元の作業はここに残る）"
    git checkout main 2>&1 | tail -2 || git checkout -B main origin/main 2>&1 | tail -2
  fi
  git branch --set-upstream-to=origin/main main 2>&1 | tail -1

  echo "--- 4. 同期を通す ---"
  git fetch origin 2>&1 | tail -2
  $G pull --rebase --autostash origin main 2>&1 | tail -3
  $G push origin main 2>&1 | tail -3

  echo "--- 5. 同期の常駐を入れる ---"
  for s in install_autopull install_autopush install_sync_watchdog; do
    f="$R/scripts/${s}.sh"
    if [ -f "$f" ]; then bash "$f" 2>&1 | tail -2; else echo "${s}.sh がまだ届いていない"; fi
  done
  launchctl list 2>/dev/null | grep -E "autopull|autopush|syncwatchdog" || echo "(常駐なし)"

  echo "--- 復旧後 ---"
  git status -sb 2>&1 | head -3
  git log -1 --format='HEAD=%h %ci %s' 2>&1
  echo "--- 共通フレーム（今夜の日次が要る）---"
  ls -l "$R/TOEcompany/メディア事業部/共通/運用/media-daily.sh" 2>&1
} > "$OUT" 2>&1

# 戻り道は AIoni 側（claude_AIR が壊れている前提のため）
cd "$HOME/AIoni" || exit 0
git add "reports/mini_repair_${STAMP}.log" >/dev/null 2>&1
$G commit -q -m "mini: 復旧の記録 ${STAMP}" >/dev/null 2>&1
git push -q origin HEAD >/dev/null 2>&1 || {
  $G pull --rebase --autostash -q origin main >/dev/null 2>&1
  git push -q origin HEAD >/dev/null 2>&1
}
exit 0

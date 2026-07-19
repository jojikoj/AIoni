#!/usr/bin/env bash
# AIの鬼 ローカル運用スクリプト
#
#   ./run.sh collect   データ収集のみ
#   ./run.sh build     サイト生成のみ
#   ./run.sh serve     生成してローカルプレビュー (http://localhost:8765)
#   ./run.sh all       収集 → 生成 → プレビュー
#   ./run.sh publish   収集 → 生成 → git commit & push（GitHub Pages が自動更新）
set -euo pipefail
cd "$(dirname "$0")"

PORT=8765

collect() { python3 -m aioni.collectors.collect_all; }
build()   { python3 -m aioni.build; }

serve() {
  SITE_BASE_URL="http://localhost:${PORT}" python3 -m aioni.build
  echo ""
  echo "▶ http://localhost:${PORT}  (Ctrl+C で停止)"
  (cd dist && python3 -m http.server "${PORT}")
}

publish() {
  collect
  build
  git add -A
  if git diff --cached --quiet; then
    echo "変更なし。push をスキップします。"
  else
    git commit -m "collect: $(date -u '+%Y-%m-%d %H:%M UTC') のデータ更新"
    git push
    echo "push 完了。GitHub Actions が公開まで進めます。"
  fi
}

case "${1:-all}" in
  collect) collect ;;
  build)   build ;;
  serve)   serve ;;
  publish) publish ;;
  all)     collect; serve ;;
  *) echo "usage: ./run.sh [collect|build|serve|all|publish]"; exit 1 ;;
esac

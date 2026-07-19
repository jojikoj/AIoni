#!/bin/bash
# dist/ を gh-pages ブランチへ公開する。
#
# 以前は dist/ 内で git init して push していたが、親リポジトリと
# 状態が混ざって「push したのに反映されない」事故が起きた。
# ここでは毎回まっさらな一時リポジトリを作って確実に上書きする。
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

python3 tools/check_links.py            # リンク切れがあればここで止める
python3 -m aioni.build

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cp -R dist/. "$TMP/"
cd "$TMP"
git init -q
git add -A
git -c user.email=noreply@anthropic.com -c user.name=deploy \
    commit -q -m "deploy $(date +%F_%H%M)"
git push -q -f "https://github.com/jojikoj/AIoni.git" HEAD:gh-pages
echo "✅ gh-pages へ push しました"

cd "$ROOT"
python3 -m aioni.indexnow            # 検索エンジンへ更新通知

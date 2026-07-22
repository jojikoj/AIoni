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
# push の認証はキーチェーン非依存にする（cronでロック時に失敗するため）。
# 詳細は UchUchU/tools/deploy.sh と同じ。gh のトークンを実行時に使う。
REPO="github.com/jojikoj/AIoni.git"
if _t=$(gh auth token 2>/dev/null) && [ -n "$_t" ]; then
  git -c credential.helper= push -q -f "https://x-access-token:${_t}@${REPO}" HEAD:gh-pages
else
  git push -q -f "https://${REPO}" HEAD:gh-pages
fi
echo "✅ gh-pages へ push しました"

cd "$ROOT"
python3 -m aioni.indexnow            # 検索エンジンへ更新通知

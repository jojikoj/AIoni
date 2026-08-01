#!/bin/bash
# dist/ を gh-pages ブランチへ公開する。
#
# 以前は dist/ 内で git init して push していたが、親リポジトリと
# 状態が混ざって「push したのに反映されない」事故が起きた。
# ここでは毎回まっさらな一時リポジトリを作って確実に上書きする。
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$(pwd)

# --- 古いコードで公開を上書きしないための確認 ---------------------------
#
# 2026-08-01 の事故：実行機(Mac mini)が main を取り込まないまま日次を回し、
# その日に入れた改修（記事末の相談バナー・関連記事欄・画像の軽量化・
# フォントの非同期読み込み）が公開サイトから丸ごと消えた。
# deploy.sh は毎回 push -f で全上書きするため、古い機械が1回走るだけで
# 新しい成果が消える。しかもエラーにはならないので気づけない。
#
# そこで公開の前に、自分の手元が origin/main より遅れていないかを見る。
# 遅れていれば取り込む。取り込めなければ、上書きせずに止める——
# 何もしない方が、新しい内容を古い内容で潰すよりましなため。
# 取得できない（ネットワーク断など）ときは、公開を止めてまで守るほどでは
# ないので警告だけ出して続ける。
if git rev-parse --git-dir >/dev/null 2>&1; then
  if git fetch -q origin main 2>/dev/null; then
    BEHIND=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)
    if [ "${BEHIND:-0}" -gt 0 ]; then
      echo "⚠️ origin/main より ${BEHIND} コミット遅れています。取り込みます。"
      if ! git merge --ff-only origin/main 2>/dev/null; then
        echo "❌ 取り込めませんでした（手元に未コミットの変更があるか、履歴が分岐しています）。" >&2
        echo "   古いコードで公開を上書きしないため、ここで中止します。" >&2
        echo "   手元を確認して 'git pull --ff-only' を通してから再実行してください。" >&2
        exit 1
      fi
      echo "   取り込みました（$(git log -1 --format=%s)）"
    fi
  else
    echo "⚠️ origin/main を取得できませんでした。手元のコードで公開を続けます。" >&2
  fi
fi

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

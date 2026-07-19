#!/bin/bash
# AIの鬼 日次更新。cron から無人で回す前提。
#
# 収集 → 翻訳 → 本文要約 → ビルド → 公開 → 検索エンジン通知。
# 途中で失敗しても次の実行で取り返せるよう、各段は独立させている
# （収集が落ちても、既存データでのビルドと公開は行う）。
#
# 課金ゼロが絶対条件のため、AIはローカルの claude CLI のみを使い、
# バッチは必ず --model haiku で回す（build.py 側ではなく collectors 内で指定）。
set -uo pipefail
cd "$(dirname "$0")/.."

# cron の既定 PATH には ~/.local/bin が含まれず、翻訳・要約に使う
# claude CLI が見つからないまま無音で失敗する。明示しておく。
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

# claude CLI の認証情報はキーチェーンにあり、その参照に USER/LOGNAME を要する。
# cron はこれらを渡さないため、無いと "Not logged in" で全件失敗する。
export USER="${USER:-$(id -un)}"
export LOGNAME="$USER"
export SHELL="${SHELL:-/bin/zsh}"
# バッチは必ず haiku。未指定だと上位モデルを使い、対話の枠まで食い潰す。
export AIONI_BATCH_MODEL=haiku

# 認証まで通るか先に確かめる。ここで落ちていれば要約は全滅するため、
# 気づかず空のまま公開し続けるより、ログに明示して止める方がよい。
if ! claude -p --model haiku "OK" >/dev/null 2>&1; then
  echo "⚠️ claude CLI が使えない（未ログイン/PATH）。要約はスキップされる。"
fi

LOG_DIR="$HOME/claude_AIR/TOEcompany/コンテンツ部/案件/AIの鬼/ログ"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/daily_$(date +%F).log"
exec >> "$LOG" 2>&1
echo "════════ $(date '+%F %T') 開始 ════════"

step() {   # step <名前> <コマンド...>
  echo "── $1"
  if "${@:2}"; then echo "   ✅ $1"; else echo "   ⚠️ $1 で失敗（続行）"; fi
}

# 1. 収集（RSS/API。無料ソースのみ）
step "収集" python3 -m aioni.collectors.collect_all

# 2. 本文取得と日本語要約
#    1回あたりの件数を絞る。全件を一度に回すと数時間かかるため、
#    毎日少しずつ消化して未処理を減らす設計にしている。
step "本文要約" python3 -m aioni.collectors.fulltext --limit=40

# 3. 内部リンク検査 → ビルド → 公開 → IndexNow
step "公開" ./tools/deploy.sh

# 4. 状況を1行で残す（週次の振り返りで読む）
python3 - <<'PY'
import json, pathlib, datetime
d = json.loads(pathlib.Path("data/news.json").read_text(encoding="utf-8"))
items = d["items"]
body = sum(1 for i in items if i.get("body_ja"))
line = (f"{datetime.date.today()}\tニュース{len(items)}\t本文{body}"
        f"\t記事{len(list(pathlib.Path('content/articles').glob('*.ja.md')))}")
p = pathlib.Path("data/daily_stats.tsv")
p.write_text((p.read_text(encoding="utf-8") if p.exists() else
              "date\tnews\tbody\tarticles\n") + line + "\n", encoding="utf-8")
print("   " + line.replace("\t", "  "))
PY

echo "════════ $(date '+%F %T') 終了 ════════"

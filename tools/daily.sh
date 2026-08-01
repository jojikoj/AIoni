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

# 0. コードの取り込み
#
#    ⚠️ 2026-08-01 に判明した事故: このスクリプトは git を一切触っていなかった。
#    実行機（Mac mini）は自分のチェックアウトのまま毎日ビルドするので、
#    別マシンで直してpushしたコードが永久に本番へ出ない。実際、7/30のSEO/AEO改修
#    （/papers/2以降のnoindex・一覧descriptionの個別化・構造化データ）が
#    2日間まったく反映されず、GSC上で /papers/N が8位前後の表示を
#    CTR 0% で吸い続けていた。「ビルドも公開も成功しているのに中身が古い」型の
#    故障で、watchdog も朝の運用チェックも検知できない。
#
#    先に pull し、最後にデータを push する（補助金の鬼 scripts/lib-git.sh と同じ方針）。
#    衝突しても日次自体は止めない。ローカルの状態で続行してログに残す。
sync_code() {
  git remote get-url origin >/dev/null 2>&1 || return 0
  git fetch origin main --quiet 2>/dev/null || { echo "   ⚠️ fetch失敗（ローカルのまま続行）"; return 1; }
  local behind
  behind=$(git rev-list --count HEAD..origin/main 2>/dev/null || echo 0)
  [ "$behind" = "0" ] && { echo "   最新（取り込むものなし）"; return 0; }
  echo "   origin/main に未取込 ${behind} 件 → 取り込む"
  if git -c user.name=daily -c user.email=noreply@anthropic.com \
       pull --rebase --autostash --quiet origin main 2>/dev/null; then
    echo "   取り込み完了: $(git log --oneline -1)"
  else
    git rebase --abort 2>/dev/null || true
    echo "   ⚠️ 取り込みが衝突。ローカルの状態で続行（要手動解消）"
    return 1
  fi
}
step "コード同期" sync_code

# 1. 収集（RSS/API。無料ソースのみ）
step "収集" python3 -m aioni.collectors.collect_all

# 2. 記事本文の取得（body_src に保存。次段の素材になる）
#    1回あたりの件数を絞る。全件を一度に回すと数時間かかるため、
#    毎日少しずつ消化して未処理を減らす設計にしている。
step "本文取得" python3 -m aioni.collectors.fulltext --limit=40

# 3. 個別ページに表示する約800字の解説（body_long）を生成する。
#
#    ⚠️ 2026-07-30 まで、この工程が daily.sh に入っていなかった。
#    fulltext は body_ja に書くが、サイト（build.py / news_article.html）が
#    読むのは body_long。つまり毎日 claude を40件叩いた結果を、サイトは
#    一度も表示していなかった。新着ニュースの個別ページは本文が空のまま
#    「出典リンクと関連記事だけ」の薄いページになっていた。
#    body_long を作るのはこのスクリプトなので、日次に入れる。
#    2026-08-01: 20→35 に増量。実測で body_long が 445/600件（未生成155件）あり、
#    未生成のページは noindex になる（build.py の thin_news）＝検索に出ない。
#    20件/日では新着に追われて在庫が減らないため、消化を優先する。
#    haiku なので追加コストは無く、所要は数分（jobs.yaml の timeout 3600 内）。
step "解説生成" python3 tools/gen_news_summaries.py --limit=35

# 4. 内部リンク検査 → ビルド → 公開 → IndexNow
step "公開" ./tools/deploy.sh

# 5. 状況を1行で残す（週次の振り返りで読む）
#    ⚠️ 2026-07-30 修正: ここは body_ja を数えていた。body_ja はサイトが
#    表示しないフィールドなので、この列が増えても記事の中身は増えていない。
#    「数字は動いているのに実物は空」という一番気づけない壊れ方だった。
#    サイトが実際に表示する body_long を数える。
python3 - <<'PY'
import json, pathlib, datetime
d = json.loads(pathlib.Path("data/news.json").read_text(encoding="utf-8"))
items = d["items"]
body = sum(1 for i in items if (i.get("body_long") or "").strip())
src = sum(1 for i in items if (i.get("body_src") or "").strip())
line = (f"{datetime.date.today()}\tニュース{len(items)}\t本文{body}"
        f"\t素材{src}"
        f"\t記事{len(list(pathlib.Path('content/articles').glob('*.ja.md')))}")
p = pathlib.Path("data/daily_stats.tsv")
p.write_text((p.read_text(encoding="utf-8") if p.exists() else
              "date\tnews\tbody\tsrc\tarticles\n") + line + "\n", encoding="utf-8")
print("   " + line.replace("\t", "  "))
PY

# --- 旬ネタ提案: いま検索/世間で伸びているAI話題を _旬ネタ/提案.md に更新 ---
python3 "$(dirname "$0")/trend_intake.py" || echo "旬ネタ提案skip"

# 6. 収集データを origin/main へ戻す
#    実行機のローカルにしか無いと、別マシンで作業したとき土台が食い違う。
#    dist/ は .gitignore 済みなので、ここで載るのは data/ と content/ の更新だけ。
sync_data() {
  git remote get-url origin >/dev/null 2>&1 || return 0
  [ -z "$(git status --porcelain)" ] && { echo "   変更なし"; return 0; }
  git add -A
  git -c user.name=daily -c user.email=noreply@anthropic.com \
      commit -q -m "日次収集: ニュース・論文データを更新（$(date +%F)）" || return 1
  git push -q origin HEAD:main 2>/dev/null || { echo "   ⚠️ push失敗（次回に持ち越し）"; return 1; }
  echo "   push完了: $(git log --oneline -1)"
}
step "データ同期" sync_data

echo "════════ $(date '+%F %T') 終了 ════════"

#!/bin/bash
# AIの鬼 日次更新。cron から無人で回す前提。
#
# 収集 → 本文取得 → 解説生成 → 旬ネタ記事 → ビルド → 公開 → 成果物を戻す。
# 途中で失敗しても次の実行で取り返せるよう、各段は独立させている
# （収集が落ちても、既存データでのビルドと公開は行う）。
#
# 課金ゼロが絶対条件のため、AIはローカルの claude CLI のみを使い、
# バッチは必ず --model haiku で回す（media_init が環境変数で固定する）。
#
# 環境の準備・ログ・git の往復は3媒体で共通なので、共通フレームに寄せてある。
# 媒体ごとの設定（ブランチ・ログ先・成果物のパス）は media.json が正本。
#
#   ⚠️ 2026-08-01 に判明した事故: 以前このスクリプトは git を一切触っていなかった。
#   実行機（Mac mini）は自分のチェックアウトのまま毎日ビルドするので、
#   別マシンで直してpushしたコードが永久に本番へ出ない。実際、7/30のSEO/AEO改修
#   （/papers/2以降のnoindex・一覧descriptionの個別化・構造化データ）が
#   2日間まったく反映されず、GSC上で /papers/N が8位前後の表示を
#   CTR 0% で吸い続けていた。「ビルドも公開も成功しているのに中身が古い」型の
#   故障で、watchdog も朝の運用チェックも検知できない。
#   いまは media_init が先に pull し、最後の media_push で成果物を戻す。
set -uo pipefail
cd "$(dirname "$0")/.."

FRAME="$HOME/claude_AIR/TOEcompany/メディア事業部/共通/運用/media-daily.sh"
if [ ! -f "$FRAME" ]; then
  echo "共通フレームが見つかりません: $FRAME" >&2
  echo "claude_AIR が同期されていない可能性があります（cd ~/claude_AIR && git pull）" >&2
  exit 1
fi
# shellcheck source=/dev/null
. "$FRAME"

media_init aioni || exit 1

# 1. 収集（RSS/API。無料ソースのみ）
media_step "収集" python3 -m aioni.collectors.collect_all

# 2. 記事本文の取得（body_src に保存。次段の素材になる）
#    1回あたりの件数を絞る。全件を一度に回すと数時間かかるため、
#    毎日少しずつ消化して未処理を減らす設計にしている。
media_step "本文取得" python3 -m aioni.collectors.fulltext --limit=40

# 3. 個別ページに表示する約800字の解説（body_long）を生成する。
#
#    ⚠️ 2026-07-30 まで、この工程が daily.sh に入っていなかった。
#    fulltext は body_ja に書くが、サイト（build.py / news_article.html）が
#    読むのは body_long。つまり毎日 claude を40件叩いた結果を、サイトは
#    一度も表示していなかった。新着ニュースの個別ページは本文が空のまま
#    「出典リンクと関連記事だけ」の薄いページになっていた。
#    2026-08-01: 20→35 に増量。未生成のページは noindex になる（thin_news）＝
#    検索に出ないため、消化を優先する。haiku なので追加コストは無い。
media_step "解説生成" python3 tools/gen_news_summaries.py --limit=35

# 3b. その日の旬ネタから記事を1本作って公開する（2026-08-13 追加・同日方針変更）
#
#     ネタはストックしない。**この日に収集したニュースから選んで、その日に書く。**
#     テーマ在庫から書くと「いつ書いても同じ記事」になり、それは既にAIが答えられる
#     一般論で引用もクリックもされない（小嶋さん指示）。
#     素材は 2 で取った原文（body_src）と 3 で作った解説（body_long）。
#     つまりこのステップは 1〜3 の後でなければ成立しない。
#
#     コーナーはネタで決まる。AI検索・AEOの話→AEO対策室／それ以外→AI解体新書。
#     実践室・失敗の鬼・中の鬼は自社の実測が要るので自動生成しない（人が書く）。
#
#     ⚠️ **検査（字数・表・まとめ・内部リンクの実在・水増し表現・裏の取れない数字）に
#     落ちたものは公開しない。** 1日空くのは構わないが、裏の取れない数字を載せると
#     「実測しか書かない」というこのサイトの前提が壊れる。落ちた下書きは
#     content/_aeo_rejected/ に残り、理由はこのログに出る（黙って0本にしない）。
#
#     ここだけ haiku を使わない。1日1本なのでバッチではなく、
#     記事の質がそのまま媒体の信用になるため（AIONI_ARTICLE_MODEL で変更可）。
export AIONI_ARTICLE_MODEL="${AIONI_ARTICLE_MODEL:-sonnet}"
media_step "旬ネタ記事" python3 tools/publish_daily.py

# 4. 内部リンク検査 → ビルド → 公開 → IndexNow
media_step "公開" ./tools/deploy.sh

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

# --- 旬ネタ提案 ---
# 主軸は trend_news.py（この1週間に実際に起きたことから選ぶ → _旬ネタ/今週.md）。
# trend_intake.py はGoogleサジェスト起点で、返るのは「ai エージェント とは」のような
# 定常的な検索意図。旬ではないうえ既存226記事とカニバるので、補助として残す。
python3 "$(dirname "$0")/trend_news.py" || echo "今週ネタskip"
python3 "$(dirname "$0")/trend_intake.py" || echo "検索語ネタskip"

# 6. 収集データと記事を origin へ戻す。
#    実行機のローカルにしか無いと、別マシンで作業したとき土台が食い違う。
#    対象は media.json の artifacts（data / content）だけ。以前は `git add -A` で
#    実験中のコードまで巻き込む可能性があった。dist/ は .gitignore 済み。
media_step "データ同期" media_push "日次収集: ニュース・論文データを更新"

media_finish

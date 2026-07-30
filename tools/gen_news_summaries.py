#!/usr/bin/env python3
"""ニュース1件ごとに「AIの鬼編集部」の約800字オリジナル解説(body_long)を生成する。

RSSの短い要約や機械翻訳(summary_ja)の代わりに、
入力の title / summary が伝える事実だけを核として、
日本の中小企業・製造業の実務家に向けた独自解説を書き起こす。
本文の転載ではなくTOEの言葉での再構成であり、出典は表示側で必ず併記する。

方針:
  - claude CLI (haiku) をバッチで叩く。API従量課金ではなく Claude Code 契約枠。
  - 1件生成するたびに news.json へ即保存する（途中で落ちても成果が残る）。
  - 連続失敗したら中断する（枠切れ・障害の暴走を防ぐ）。
  - すでに body_long がある記事は既定でスキップ（手動の高品質要約を温存）。
    作り直したいときは --force。

使い方:
  python3 tools/gen_news_summaries.py --limit=5      # まず数件だけ試作
  python3 tools/gen_news_summaries.py                # 未生成の全件
  python3 tools/gen_news_summaries.py --force        # 既存も作り直す
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from aioni.build import news_slug  # noqa: E402
from aioni.collectors.translate import clean_for_translation  # noqa: E402

NEWS_PATH = Path(__file__).resolve().parent.parent / "data" / "news.json"

CLAUDE_BIN = os.environ.get("AIONI_CLAUDE_BIN") or shutil.which("claude")
# 800字×複数件は重いので1プロンプト4件。品質と枠のバランス。
BATCH = int(os.environ.get("AIONI_SUMMARY_BATCH", "4"))
TIMEOUT = int(os.environ.get("AIONI_SUMMARY_TIMEOUT", "300"))
MODEL = os.environ.get("AIONI_BATCH_MODEL", "haiku")
MAX_CONSECUTIVE_FAIL = 3

TARGET_MIN, TARGET_MAX = 720, 900  # 目標字数の許容幅（空白除く）

PROMPT_HEAD = """あなたはAIメディア「AIの鬼」の編集者です。
「AIの鬼」は、AIを実際に触って検証し、建前を抜きにした本音で語るのが売りの媒体です。
読者は日本の中小企業・製造業の経営者や実務担当者で、専門家ではありません。

以下のJSONは各AI関連ニュースの見出しと要約です。1件ごとに、
そのニュースを扱った日本語のオリジナル解説記事（本文のみ、約800字）を書いてください。

article_body があるものは、それが配信元の記事本文です。事実はそこから取ってください
（無いものは title / summary の範囲だけで書き、足りない分は事実を作らずに
業界文脈と実務含意で厚みを出してください）。

【構成】各記事は次の流れで、見出し記号や箇条書きを使わず段落で書く（2〜4段落）:
  1. 何が起きたのか（入力の事実を、自分の言葉で分かりやすく言い直す）
  2. AIの鬼の視点 — ここが主役。「面白いのはここ」「引っかかるのはここ」
     「業界的にはこういう意味だ」といった独自の切り口・本音・比喩を1つは入れる。
     横並びの通信社原稿には無い、読んで思わず膝を打つ角度を必ず添える。
  3. 中小企業の実務にどう効くか（明日の仕事で使える一言に落とす）

【厳守】
  - 事実の捏造は禁止。入力に無い固有の数値・日付・企業名・人名・製品名を新たに作らない。
    素材が薄いニュースは、事実を無理に盛らず、業界文脈や実務含意の側で厚みを出す。
  - 「独自視点・面白い視点」は事実の解釈・切り口・比喩であって、事実の水増しではない。
  - 常体（だ・である）で書く。企業名・製品名は原綴り（GPT-5, Claude, Hugging Face 等）。
  - 「出典」「元記事」への言及や URL は本文に書かない（表示側で併記するため）。
  - 前置き・見出し・箇条書き・コードフェンスは書かない。本文の段落だけ。

【出力】入力と同じキー構造のJSONのみ。各値は body_long の本文文字列。
例: {"0": "……(約800字の本文)……", "1": "……"}

入力:
"""


def load() -> dict:
    return json.loads(NEWS_PATH.read_text(encoding="utf-8"))


def save(data: dict) -> None:
    tmp = NEWS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(NEWS_PATH)


def _extract_json(text: str) -> dict | None:
    if not text:
        return None
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def _call(payload: dict) -> dict | None:
    prompt = PROMPT_HEAD + json.dumps(payload, ensure_ascii=False, indent=1)
    try:
        proc = subprocess.run(
            [CLAUDE_BIN, "--model", MODEL, "-p", prompt],
            capture_output=True, text=True, timeout=TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"    [claude] 呼び出し失敗: {type(e).__name__}", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(f"    [claude] exit={proc.returncode}: {proc.stderr[:200]}", file=sys.stderr)
        return None
    return _extract_json(proc.stdout)


def _material(it: dict) -> dict:
    """生成の入力素材。日本語訳があれば読みやすさのため併記する。

    body_src（aioni.collectors.fulltext が取得した記事本文）があれば入れる。
    2026-07-30 まではRSSの紹介文だけを素材に約800字を書かせていたため、
    素材が薄い記事で水増しに寄りやすかった。本文があるならそれを読ませる。
    """
    m = {
        "title": clean_for_translation(it.get("title", "")),
        "title_ja": (it.get("title_ja") or "").strip(),
        "summary": clean_for_translation(it.get("summary", "")),
        "summary_ja": (it.get("summary_ja") or "").strip(),
    }
    src = (it.get("body_src") or "").strip()
    if src:
        # 長い本文はプロンプトを膨らませるので先頭のみ（結論が先の記事が多い）
        m["article_body"] = src[:4000]
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="生成する最大件数（0=全件）")
    ap.add_argument("--force", action="store_true", help="既存 body_long も作り直す")
    args = ap.parse_args()

    if not CLAUDE_BIN:
        print("claude CLI が見つかりません。中止します。", file=sys.stderr)
        return 1

    data = load()
    items = data.get("items", [])
    targets = [
        it for it in items
        if it.get("title")
        and not it.get("body_skip")
        and (args.force or not (it.get("body_long") or "").strip())
    ]
    if args.limit:
        targets = targets[:args.limit]
    print(f"生成対象 {len(targets)} 件 / 全 {len(items)} 件（model={MODEL}, batch={BATCH}）")

    done = 0
    consecutive_fail = 0
    for i in range(0, len(targets), BATCH):
        chunk = targets[i:i + BATCH]
        payload = {str(n): _material(it) for n, it in enumerate(chunk)}
        result = _call(payload)
        if not result:
            consecutive_fail += 1
            print(f"    batch {i // BATCH + 1} 失敗（連続 {consecutive_fail}）", file=sys.stderr)
            if consecutive_fail >= MAX_CONSECUTIVE_FAIL:
                print("連続失敗が上限に達したため中断します。", file=sys.stderr)
                break
            continue
        consecutive_fail = 0
        for n, it in enumerate(chunk):
            body = (result.get(str(n)) or "").strip()
            body = re.sub(r"\n{3,}", "\n\n", body)
            length = len(re.sub(r"\s", "", body))
            if length < 400:  # 明らかに生成失敗（極端に短い）はスキップ
                print(f"    ! {news_slug(it)} 短すぎ({length}字) — 未更新", file=sys.stderr)
                continue
            it["body_long"] = body
            it["body_long_by"] = "aioni-editor"
            done += 1
        save(data)  # バッチごとに逐次保存
        print(f"    {min(i + BATCH, len(targets))}/{len(targets)} 生成済み（保存済）")

    print(f"完了: body_long を {done} 件生成・保存しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""各ニュースに「記事固有のFAQ主問い(faq_q)」を生成する。

FAQの1問目を全記事同一の「このニュースの要点は？」から、その記事だけの
具体的な問い（例:「Kimi K3とは何か？」「AIエージェント攻撃はどう防ぐ？」）に
変えると、AI検索・検索エンジンがユーザーの実クエリと一致させて引用しやすくなる。

body_long(800字の本文)を素材に、読者が検索窓に打ちそうな短い問いを1つ作る。
軽い処理なので1バッチに多く詰め、haiku で速く回す。逐次保存・連続失敗で中断。

使い方:
  python3 tools/gen_faq_questions.py            # faq_q 未生成の全件
  python3 tools/gen_faq_questions.py --force     # 作り直す
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

NEWS_PATH = Path(__file__).resolve().parent.parent / "data" / "news.json"
CLAUDE_BIN = os.environ.get("AIONI_CLAUDE_BIN") or shutil.which("claude")
BATCH = int(os.environ.get("AIONI_FAQ_BATCH", "16"))
TIMEOUT = int(os.environ.get("AIONI_FAQ_TIMEOUT", "240"))
MODEL = os.environ.get("AIONI_BATCH_MODEL", "haiku")
MAX_FAIL = 3

PROMPT_HEAD = """あなたはAIメディア「AIの鬼」の編集者です。
以下のJSONは各ニュース記事の見出しと本文（日本語）です。1件ごとに、
その記事の内容について読者が検索窓に打ちそうな『記事固有の問い』を1つ作ってください。

要件:
  - 20〜30字程度の疑問文。末尾は「？」。
  - その記事だけに当てはまる具体的な問いにする（固有名詞や論点を入れる）。
    例「Kimi K3とは何か？」「AIエージェントの攻撃はどう防ぐ？」
  - 「このニュースの要点は？」のような汎用文は禁止。
  - 本文に無い事実を作らない。
  - 出力は入力と同じキー構造のJSONのみ。各値は問い文字列。前置き・説明は書かない。

入力:
"""


def _extract_json(text):
    if not text:
        return None
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        return None
    try:
        return json.loads(text[a:b + 1])
    except json.JSONDecodeError:
        return None


def _call(payload):
    prompt = PROMPT_HEAD + json.dumps(payload, ensure_ascii=False, indent=1)
    try:
        proc = subprocess.run([CLAUDE_BIN, "--model", MODEL, "-p", prompt],
                              capture_output=True, text=True, timeout=TIMEOUT)
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"    [claude] 失敗: {type(e).__name__}", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(f"    [claude] exit={proc.returncode}", file=sys.stderr)
        return None
    return _extract_json(proc.stdout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    if not CLAUDE_BIN:
        print("claude CLI が見つかりません。", file=sys.stderr)
        return 1

    data = json.loads(NEWS_PATH.read_text(encoding="utf-8"))
    items = data.get("items", [])
    targets = [it for it in items
               if (it.get("body_long") or "").strip()
               and (args.force or not (it.get("faq_q") or "").strip())]
    if args.limit:
        targets = targets[:args.limit]
    print(f"faq_q 生成対象 {len(targets)} 件（model={MODEL}, batch={BATCH}）")

    done = fail = 0
    for i in range(0, len(targets), BATCH):
        chunk = targets[i:i + BATCH]
        payload = {str(n): {"title": it.get("display_title") or it.get("title", ""),
                            "body": (it.get("body_long") or "")[:600]}
                   for n, it in enumerate(chunk)}
        res = _call(payload)
        if not res:
            fail += 1
            if fail >= MAX_FAIL:
                print("連続失敗が上限。中断します。", file=sys.stderr)
                break
            continue
        fail = 0
        for n, it in enumerate(chunk):
            q = (res.get(str(n)) or "").strip()
            if q and q.endswith("？") and len(q) <= 40:
                it["faq_q"] = q
                done += 1
        NEWS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                             encoding="utf-8")
        print(f"    {min(i + BATCH, len(targets))}/{len(targets)} 生成（保存済）")
    print(f"完了: faq_q を {done} 件生成。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

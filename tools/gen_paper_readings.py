"""arXiv 論文の「日本語の読み解き」を生成する（個別ページ用）。

なぜ作るか（2026-07-30 実測）:
  /papers/ は一覧のページネーションしか存在せず、表示回数の23%を吸って
  CTRは1.7%だった。arXivの英語タイトルで一覧ページが検索に当たり、
  読者はクリックしても「英語の要旨が並んだ一覧」に着地して答えが無い。
  そこで注目論文だけ個別ページを持たせ、日本語の読み解きを載せる。

なぜ全件やらないか:
  250件すべてに薄いページを作ると、ニュース集約で避けたはずの
  「他社コンテンツを膨らませた大量ページ」を論文側で再生産することになる。
  上限を LIMIT 本に絞り、残りは一覧のままにする。

課金ゼロの制約:
  要約はローカルの claude CLI（--model haiku 固定）で作る。
  入力は data/papers.json にすでにある英語要旨だけ。外部から新しい情報は
  取らない（取れば裏取りが必要になり、無人運用にできない）。

出力: data/paper_readings.json
  { "generated_at": ..., "items": { "<arxiv_id>": {...} } }

実行:
    python3 tools/gen_paper_readings.py            # 未生成のものだけ作る
    python3 tools/gen_paper_readings.py --limit=6
    python3 tools/gen_paper_readings.py --force    # 既存も作り直す
"""
from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import subprocess
import sys
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
PAPERS = ROOT / "data" / "papers.json"
OUT = ROOT / "data" / "paper_readings.json"

# 個別ページを持たせる本数の上限。
# 増やすほど「薄いページの量」に近づくので、安易に上げない。
LIMIT = 12

# 対象カテゴリ。中小企業の実務に届きうる領域に絞る。
# cs.AI=人工知能 / cs.CL=自然言語処理 / cs.LG=機械学習
TARGET_CATEGORIES = ("cs.AI", "cs.CL", "cs.LG")

# カテゴリだけで絞ると、cs.LG には医療画像・金融ボラティリティ・
# 固有値正則化のような基礎研究が大量に入る。読者（中小企業の経営者・情シス）
# にとって無価値なページを作らないよう、実務に触れる語で加点して選ぶ。
# 「新着順で機械的に12本」ではなく「実務に触れる論文のうち新しい12本」。
_PRACTICAL = {
    # 使う対象
    "llm": 3, "language model": 3, "agent": 3, "chatbot": 3, "rag": 3,
    "retrieval-augmented": 3, "tool use": 3, "tool-use": 3, "prompt": 2,
    "code": 2, "coding": 2, "software engineering": 3, "document": 2,
    "spreadsheet": 3, "workflow": 3, "multi-agent": 3, "fine-tun": 2,
    # 実務で効く観点
    "cost": 3, "efficien": 2, "latency": 2, "deploy": 2, "production": 3,
    "enterprise": 3, "business": 3, "reliab": 2, "hallucinat": 3,
    "benchmark": 1, "evaluat": 1, "safety": 2, "privacy": 2, "on-device": 2,
    "quantiz": 1, "inference": 2, "small model": 3, "distill": 1,
}
# これが入っていたら、実務向けページとしては採らない（専門領域の基礎研究）
_EXCLUDE = (
    "cancer", "tumor", "patient", "clinical", "eeg", "mri", "ct scan",
    "protein", "molecul", "genom", "drug discovery", "diagnosis",
    "volatility", "stock price", "portfolio", "asset pricing",
    "astronom", "cosmolog", "seismic", "weather forecast", "crystal",
    "lunar", "moon's surface", "remote sensing", "satellite imagery",
)
MIN_PRACTICAL_SCORE = 5

MODEL = os.environ.get("AIONI_BATCH_MODEL", "haiku")

PROMPT = """あなたは中小企業の経営者・情報システム担当向けに、AIの論文を読み解く編集者です。
以下はarXivに投稿された論文の「英語タイトル」と「英語要旨（冒頭のみ）」です。
これだけを根拠に、日本語で読み解いてください。

厳守事項:
- 要旨に書かれていないことは絶対に書かない。数字を創作しない。
- 要旨だけでは分からないことは「要旨からは不明」と書く。
- 「〜だろう」「〜と考えられる」のような推測は、推測であることを明示する。
- 誇張しない。「画期的」「革命的」のような語を使わない。

次のJSONだけを出力してください（前後に説明文をつけない）:
{{
  "title_ja": "日本語のタイトル（30〜60字。原題の直訳ではなく内容が分かる形に）",
  "one_line": "この論文が何を示したかを1文で（60〜100字）",
  "points": ["要旨から読み取れる要点1", "要点2", "要点3"],
  "implication": "中小企業の実務にとって何を意味するか（100〜200字）。実務に直接関係しない基礎研究なら、正直にそう書く。"
}}

英語タイトル: {title}

英語要旨（冒頭）: {summary}
"""


def _listify(value) -> list[str]:
    """papers.json の categories/authors は "['cs.AI', 'cs.CV']" のような
    Python リテラル文字列で入っている。安全に配列へ戻す。"""
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str) and value.startswith("["):
        try:
            parsed = ast.literal_eval(value)
            if isinstance(parsed, (list, tuple)):
                return [str(v) for v in parsed]
        except (ValueError, SyntaxError):
            pass
    return [value] if value else []


def arxiv_id(url: str) -> str:
    """https://arxiv.org/abs/2607.22535v1 → 2607.22535"""
    m = re.search(r"/abs/([0-9]+\.[0-9]+)", url or "")
    return m.group(1) if m else ""


def practical_score(title: str, summary: str) -> int:
    """中小企業の実務にどれだけ触れるかを点数化する。0なら実務向けでない。"""
    text = f"{title} {summary}".lower()
    if any(x in text for x in _EXCLUDE):
        return 0
    return sum(w for kw, w in _PRACTICAL.items() if kw in text)


def pick(items: list[dict], limit: int) -> list[dict]:
    """個別ページを持たせる論文を選ぶ。

    選び方（あとから説明できる基準にする）:
      1. 主カテゴリが cs.AI / cs.CL / cs.LG
      2. 実務キーワードのスコアが MIN_PRACTICAL_SCORE 以上
         （医療・金融・物理など専門領域の基礎研究は除外）
      3. 残ったものを新しい順に limit 本

    引用数のような品質指標は取得できないため、恣意的な「注目」判定はしない。
    「実務に触れる論文のうち新しいもの」という機械的な基準にとどめる。
    """
    out = []
    for it in items:
        cats = _listify(it.get("categories"))
        if not cats or cats[0] not in TARGET_CATEGORIES:
            continue
        if not arxiv_id(it.get("url", "")):
            continue
        score = practical_score(it.get("title", ""), it.get("summary", ""))
        if score < MIN_PRACTICAL_SCORE:
            continue
        it = dict(it)
        it["_score"] = score
        out.append(it)
    out.sort(key=lambda x: x.get("published", ""), reverse=True)
    return out[:limit]


def ask(title: str, summary: str) -> dict | None:
    prompt = PROMPT.format(title=title, summary=summary[:1200])
    try:
        res = subprocess.run(
            ["claude", "-p", "--model", MODEL, prompt],
            capture_output=True, text=True, timeout=300)
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        print(f"    ⚠️ {type(e).__name__}")
        return None
    if res.returncode != 0:
        print(f"    ⚠️ claude 終了コード {res.returncode}: {res.stderr[:160]}")
        return None
    text = res.stdout.strip()
    # ```json ... ``` で囲まれて返ることがある
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        print(f"    ⚠️ JSONが見つからない: {text[:120]}")
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        print(f"    ⚠️ JSON壊れ: {e}")
        return None
    # 必須項目がそろっているかだけ検査する（中身の正しさは人が読む）
    for key in ("title_ja", "one_line", "points", "implication"):
        if not data.get(key):
            print(f"    ⚠️ {key} が空")
            return None
    if not isinstance(data["points"], list):
        return None
    return data


def main() -> int:
    limit = LIMIT
    force = "--force" in sys.argv
    for a in sys.argv[1:]:
        if a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])

    if not PAPERS.exists():
        print("data/papers.json がありません")
        return 1
    items = json.loads(PAPERS.read_text(encoding="utf-8")).get("items", [])
    targets = pick(items, limit)
    print(f"対象 {len(targets)}本（全 {len(items)}本中 / モデル {MODEL}）")

    store = {"items": {}}
    if OUT.exists() and not force:
        store = json.loads(OUT.read_text(encoding="utf-8"))
        store.setdefault("items", {})

    fails = 0
    for i, it in enumerate(targets, 1):
        aid = arxiv_id(it["url"])
        if aid in store["items"] and not force:
            print(f"[{i}/{len(targets)}] {aid} 既存（スキップ）")
            continue
        print(f"[{i}/{len(targets)}] {aid} {it['title'][:60]}")
        data = ask(it.get("title", ""), it.get("summary", ""))
        if not data:
            fails += 1
            # 連続失敗はモデル未ログイン等の構造的な問題。早めに止める。
            if fails >= 3:
                print("連続3件失敗。中断します（生成済みは保存）。")
                break
            continue
        fails = 0
        data.update({
            "arxiv_id": aid,
            "title_en": it.get("title", ""),
            "url": it.get("url", ""),
            "pdf": it.get("pdf", ""),
            "published": it.get("published", ""),
            "categories": _listify(it.get("categories")),
            "authors": _listify(it.get("authors")),
            "summary_en": it.get("summary", ""),
            "by": f"aioni-editor/{MODEL}",
        })
        store["items"][aid] = data
        # 1件ずつ保存する。途中で落ちても積み上がった分は残す。
        store["generated_at"] = datetime.now(timezone.utc).isoformat()
        OUT.write_text(json.dumps(store, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        print(f"    ✅ {data['title_ja'][:50]}")

    print(f"→ {OUT} に {len(store['items'])}件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

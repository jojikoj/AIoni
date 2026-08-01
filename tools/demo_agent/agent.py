#!/usr/bin/env python3
"""問い合わせ一次対応エージェント（製造業向けのデモ）。

何のためのコードか:
    AIエージェントの案件を取りたいが、「AIエージェントで何ができるのか」を
    言葉で説明しても中小企業には伝わらない。実際に動くものを見せるのが早い。
    これはそのデモであり、そのまま提案の実演に使う。

    題材は板金加工業の「見積依頼メールの一次対応」。どの製造業でも
    同じ形の仕事があり、どこも人がやっている。

設計の要点（ここが提案で一番伝えたいこと）:
    **AIに判断させない。AIは読み取りと作文だけ担当する。**

      工程1  メール本文 → 構造化（材質・板厚・加工・数量・納期）  … AI
      工程2  設備マスタと照合して受注可否を決める                … Python（ルール）
      工程3  過去案件から類似案件を探して単価の目安を出す         … Python（検索）
      工程4  返信文の下書きを書く                               … AI
      工程5  自信のないものは人間に回す                          … Python（ルール）

    「加工できるか」「いくらか」をAIに判断させると、
    もっともらしい嘘が混ざる。設備マスタに無い板厚を「対応可能です」と
    返信した時点で、この仕組みは会社にとって損失にしかならない。
    判断は必ず自社データとルールで行い、AIには文章の入口と出口だけをやらせる。

実行:
    python3 tools/demo_agent/agent.py                 # inbox/ の全件を処理
    python3 tools/demo_agent/agent.py --only 001      # 1件だけ
    python3 tools/demo_agent/agent.py --model haiku   # 既定は haiku

    ⚠ データはすべて架空。実在の企業・取引ではない。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
JST = timezone(timedelta(hours=9))

CLAUDE_BIN = os.environ.get("AIONI_CLAUDE_BIN") or shutil.which("claude")
MODEL = os.environ.get("AIONI_BATCH_MODEL", "haiku")
TIMEOUT = 120

# 材質の表記ゆれ。客は正式な記号で書かない。
# 「ステンレス」「SUS304」「SUS 304」がすべて同じ棚を指すよう寄せる。
#
# ⚠ 2026-08-01 の実行で事故った箇所。単純な部分一致で判定していたため、
#   チタン合金「Ti-6Al-4V」の中の "al" を拾って**アルミと判定**し、
#   対応できない材質に「対応可能です」と自動返信するところだった。
#   AIの誤りではなく、こちらのルールの穴。判定をAIから引き剥がしても、
#   引き剥がした先のコードが雑なら同じ事故が起きる。
#   対策は2つ: ①短い英字記号は語として独立しているときだけ一致させる
#            ②複数の材質に当たったら決めつけず、人間に回す
MATERIAL_ALIASES = {
    "SUS": ["sus", "ステンレス", "stainless", "sus304", "sus316", "sus430"],
    "SPCC": ["spcc", "鉄", "軟鋼", "冷間圧延鋼板", "sphc", "ss400"],
    "SECC": ["secc", "電気亜鉛メッキ", "ボンデ"],
    "AL": ["al", "アルミ", "aluminum", "aluminium", "a5052", "a1050", "a6063"],
    "TI": ["ti", "チタン", "titanium"],
}

# 上のうち、他の記号の一部として現れやすい短い綴り。
# これらは前後が英数字・ハイフンでないときだけ材質記号とみなす。
SHORT_CODES = {"al", "ti", "sus", "ss400"}

EXTRACT_PROMPT = """\
あなたは板金加工会社の受付担当です。取引先から届いた見積依頼メールを読み、
記載されている事実だけを構造化してください。

重要な制約:
- メールに書かれていないことは推測しないでください。書かれていなければ null にします。
- 「たぶんこうだろう」で埋めないでください。埋めた瞬間に、この仕組みは使えなくなります。
- 加工できるかどうか、いくらかは判断しないでください。それは別の工程が行います。

次のJSONだけを出力してください（説明文は不要）:
{
  "company": "差出人の会社名（分かれば。なければ null）",
  "person": "差出人の氏名（分かれば。なければ null）",
  "material_raw": "メールに書かれた材質の表記そのまま（なければ null）",
  "thickness_mm": 板厚の数値（なければ null）,
  "processes": ["レーザー切断", "ベンディング", "溶接", "タレパン" のうち該当するもの。不明なら空配列。
                表記の読み替えは行ってよい（推測ではなく言い換えのため）:
                「切断」「カット」「抜き」→ レーザー切断 /
                「曲げ」「ベンダー」「箱曲げ」→ ベンディング /
                「溶接」「ウェルド」→ 溶接 /
                「パンチ」「タレパン」「タレットパンチ」→ タレパン],
  "qty": 数量の数値（なければ null）,
  "size_note": "寸法に関する記述（なければ null）",
  "lead_note": "納期に関する記述（なければ null）",
  "lead_days": 納期の日数（換算できれば数値。できなければ null）,
  "intent": "quote"（見積依頼）/ "capability"（対応可否の問い合わせ）/ "other" のいずれか,
  "missing": ["見積に必要だが書かれていない項目の名前"]
}

--- メール本文 ---
"""

REPLY_PROMPT = """\
あなたは板金加工会社の営業担当です。下記の「判定結果」に厳密に従って、
取引先への返信メールの下書きを書いてください。

厳守:
- 判定結果にない条件を、勝手に付け加えないでください。
- 「対応可能」と書けるのは、判定結果が accept のときだけです。
- **金額・単価には一切触れないでください。** 見積は担当者が別途出します。
- 納期を約束しないでください。「最短◯日から」という書き方にしてください。
- 誇張しないでください。丁寧だが簡潔に、10行程度で書いてください。

本文だけを出力してください（件名や署名は不要）。

--- 判定結果 ---
"""


def load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        body = [ln for ln in f if not ln.lstrip().startswith("#")]
    return list(csv.DictReader(body))


def norm_material(raw: str | None) -> str | None:
    """客の書いた材質表記を、設備マスタの区分に寄せる。

    決められないときは None を返す（＝人間に回る）。
    ここで無理に1つに決めるより、判断を人間に渡すほうが安い。
    """
    if not raw:
        return None
    low = str(raw).lower().replace(" ", "").replace("　", "")

    hits = set()
    for key, words in MATERIAL_ALIASES.items():
        for w in words:
            if w in SHORT_CODES:
                # 「Ti-6Al-4V」の "al" のように、他の記号の一部として
                # 現れているものは材質記号とみなさない。
                if re.search(rf"(?<![a-z0-9\-]){re.escape(w)}(?![a-z0-9\-])", low):
                    hits.add(key)
            elif w in low:
                hits.add(key)

    if len(hits) == 1:
        return hits.pop()
    return None  # 0件＝分からない / 2件以上＝どちらとも取れる。どちらも人間へ


def call_claude(prompt: str, model: str) -> tuple[str | None, float]:
    """claude CLI を1回叩く。戻り値は (出力, 所要秒)。"""
    if not CLAUDE_BIN:
        return None, 0.0
    t0 = time.time()
    try:
        proc = subprocess.run([CLAUDE_BIN, "--model", model, "-p", prompt],
                              capture_output=True, text=True, timeout=TIMEOUT)
    except (subprocess.TimeoutExpired, OSError) as ex:
        print(f"    [claude] 失敗: {type(ex).__name__}", file=sys.stderr)
        return None, time.time() - t0
    dt = time.time() - t0
    if proc.returncode != 0:
        print(f"    [claude] exit={proc.returncode}: {proc.stderr[:160]}", file=sys.stderr)
        return None, dt
    return proc.stdout, dt


def extract_json(text: str) -> dict | None:
    fence = re.search(r"```(?:json)?\s*(.+?)```", text, re.S)
    if fence:
        text = fence.group(1)
    s, e = text.find("{"), text.rfind("}")
    if s < 0 or e <= s:
        return None
    try:
        return json.loads(text[s:e + 1])
    except json.JSONDecodeError:
        return None


def judge(rec: dict, equip: list[dict]) -> dict:
    """設備マスタと照合して受注可否を決める。ここにAIは一切関与しない。

    戻り値の decision:
      accept    … 設備で対応できる。返信を自動生成してよい
      reject    … 対応できないことが設備マスタから確定する
      escalate  … 判断に必要な情報が足りない。人間に回す
    """
    mat = norm_material(rec.get("material_raw"))
    th = rec.get("thickness_mm")
    procs = rec.get("processes") or []
    reasons: list[str] = []

    # 情報が足りない → 判断しない。ここで無理に決めるのが一番危ない。
    missing = []
    if not mat:
        missing.append("材質")
    if th is None:
        missing.append("板厚")
    if not procs:
        missing.append("加工内容")
    if missing:
        return {"decision": "escalate", "reasons": [f"{'・'.join(missing)}が不明"],
                "material": mat, "matched": []}

    # 設備マスタに1行でも該当しなければ、対応できない
    matched, ng = [], []
    for p in procs:
        rows = [r for r in equip if r["process"] == p and r["material"] == mat]
        if not rows:
            ng.append(f"{p}は{mat}に対応していない")
            continue
        ok = [r for r in rows
              if float(r["thickness_min"]) <= float(th) <= float(r["thickness_max"])]
        if not ok:
            lim = max(float(r["thickness_max"]) for r in rows)
            ng.append(f"{p}の{mat}は板厚{lim}mmまで（依頼は{th}mm）")
            continue
        matched.append({"process": p, "lead_days_min": int(ok[0]["lead_days_min"])})

    if ng:
        return {"decision": "reject", "reasons": ng, "material": mat, "matched": matched}

    lead = max((m["lead_days_min"] for m in matched), default=0)
    reasons.append(f"{mat} {th}mm の{'・'.join(procs)}は設備で対応可能")

    # 納期が最短日数を下回る依頼は、可否と切り離して人間に回す。
    # 「できます」と自動返信して落とすのが、この手の仕組みで一番多い事故。
    want = rec.get("lead_days")
    if want is not None and want < lead:
        return {"decision": "escalate",
                "reasons": reasons + [f"希望納期{want}日は最短{lead}日を下回る"],
                "material": mat, "matched": matched, "lead_days_min": lead}

    return {"decision": "accept", "reasons": reasons, "material": mat,
            "matched": matched, "lead_days_min": lead}


def find_similar(rec: dict, mat: str | None, jobs: list[dict]) -> list[dict]:
    """過去案件から似た仕事を探す。単なる絞り込みで、AIは使わない。

    近さの順に並べる: 同じ材質 → 板厚が近い → 加工の重なりが多い。
    """
    if not mat:
        return []
    th = rec.get("thickness_mm")
    procs = set(rec.get("processes") or [])
    out = []
    for j in jobs:
        if norm_material(j["material"]) != mat:
            continue
        d_th = abs(float(j["thickness"]) - float(th)) if th is not None else 99
        overlap = len(procs & set(j["process"].split("+")))
        out.append((d_th, -overlap, j))
    out.sort(key=lambda x: (x[0], x[1]))
    return [j for _, _, j in out[:3]]


def process_one(path: Path, equip: list[dict], jobs: list[dict], model: str) -> dict:
    mail = path.read_text(encoding="utf-8")
    log = {"file": path.name, "steps": {}, "ai_calls": 0, "ai_seconds": 0.0}
    t_all = time.time()

    # 工程1: 読み取り（AI）
    raw, dt = call_claude(EXTRACT_PROMPT + mail, model)
    log["ai_calls"] += 1
    log["ai_seconds"] += dt
    log["steps"]["extract_sec"] = round(dt, 2)
    rec = extract_json(raw or "")
    if rec is None:
        log["decision"] = "escalate"
        log["reasons"] = ["メールの読み取りに失敗した"]
        log["total_sec"] = round(time.time() - t_all, 2)
        log["failed"] = True
        return log
    log["extracted"] = rec

    # 工程2: 設備マスタと照合（ルール／AIなし）
    t0 = time.time()
    v = judge(rec, equip)
    log["steps"]["judge_sec"] = round(time.time() - t0, 3)
    log["decision"] = v["decision"]
    log["reasons"] = v["reasons"]

    # 工程3: 類似案件の検索（ルール／AIなし）
    t0 = time.time()
    sim = find_similar(rec, v.get("material"), jobs)
    log["steps"]["similar_sec"] = round(time.time() - t0, 3)
    log["similar"] = [{"job_no": s["job_no"], "material": s["material"],
                       "thickness": s["thickness"], "qty": s["qty"],
                       "unit_price_yen": s["unit_price_yen"]} for s in sim]

    # 過去案件の単価は「担当者へのメモ」に回す。返信本文には絶対に載せない。
    # 過去単価は条件が違えば当てにならないうえ、自動返信で客に出した金額は
    # 事実上の提示価格になる。値決めは人間の仕事として残す。
    if sim:
        prices = [int(s["unit_price_yen"]) for s in sim]
        log["internal_note"] = (
            f"参考: 類似{len(sim)}件の単価 {min(prices):,}〜{max(prices):,}円"
            f"（{ '、'.join(s['job_no'] for s in sim) }）。条件が異なるため要査定。"
        )

    # 工程4: 返信の下書き（AI）。escalate のときは書かない——
    # 人間が判断する案件に下書きを付けると、そのまま送られる事故が起きる。
    if v["decision"] in ("accept", "reject"):
        brief = {
            "decision": v["decision"],
            "reasons": v["reasons"],
            "company": rec.get("company"),
            "person": rec.get("person"),
            "material": rec.get("material_raw"),
            "thickness_mm": rec.get("thickness_mm"),
            "processes": rec.get("processes"),
            "qty": rec.get("qty"),
            "lead_days_min": v.get("lead_days_min"),
        }
        reply, dt = call_claude(
            REPLY_PROMPT + json.dumps(brief, ensure_ascii=False, indent=1), model)
        log["ai_calls"] += 1
        log["ai_seconds"] += dt
        log["steps"]["reply_sec"] = round(dt, 2)
        log["reply"] = (reply or "").strip() or None
        if not log["reply"]:
            log["failed"] = True

    log["ai_seconds"] = round(log["ai_seconds"], 2)
    log["total_sec"] = round(time.time() - t_all, 2)
    return log


def main() -> int:
    ap = argparse.ArgumentParser(description="問い合わせ一次対応エージェント（デモ）")
    ap.add_argument("--only", help="この番号のメールだけ処理する（例: 001）")
    ap.add_argument("--model", default=MODEL, help="claude CLI のモデル（既定 haiku）")
    ap.add_argument("--outdir", default=str(HERE / "out"))
    args = ap.parse_args()

    if not CLAUDE_BIN:
        print("✗ claude CLI が見つかりません", file=sys.stderr)
        return 1

    equip = load_csv(HERE / "data" / "equipment.csv")
    jobs = load_csv(HERE / "data" / "past_jobs.csv")
    mails = sorted((HERE / "inbox").glob("*.txt"))
    if args.only:
        mails = [m for m in mails if m.stem == args.only]
    if not mails:
        print("✗ 処理対象のメールがありません")
        return 1

    print(f"■ 問い合わせ {len(mails)}件 / 設備マスタ {len(equip)}行 / 過去案件 {len(jobs)}件")
    print(f"  モデル: {args.model}（読み取りと作文のみ。可否と単価の判断には使わない）\n")

    t0 = time.time()
    logs = []
    for m in mails:
        r = process_one(m, equip, jobs, args.model)
        logs.append(r)
        mark = {"accept": "✓ 自動返信", "reject": "✓ 自動返信（お断り）",
                "escalate": "→ 人間へ"}.get(r["decision"], "?")
        print(f"  [{m.stem}] {mark}  {r['total_sec']}秒  {'／'.join(r['reasons'])[:60]}")

    total = round(time.time() - t0, 1)
    n = len(logs)
    auto = sum(1 for r in logs if r["decision"] in ("accept", "reject"))
    esc = sum(1 for r in logs if r["decision"] == "escalate")
    failed = sum(1 for r in logs if r.get("failed"))
    ai_calls = sum(r["ai_calls"] for r in logs)
    ai_sec = round(sum(r["ai_seconds"] for r in logs), 1)

    summary = {
        "ran_at": datetime.now(JST).isoformat(timespec="seconds"),
        "model": args.model,
        "mails": n,
        "auto_replied": auto,
        "escalated": esc,
        "failed": failed,
        "total_sec": total,
        "avg_sec": round(total / n, 1) if n else 0,
        "ai_calls": ai_calls,
        "ai_seconds": ai_sec,
        "results": logs,
    }
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(JST).strftime("%Y%m%d-%H%M%S")
    out = outdir / f"run-{stamp}.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n■ 結果 {n}件 / 自動返信 {auto}件 / 人間へ {esc}件 / 失敗 {failed}件")
    print(f"  所要 {total}秒（1件あたり {summary['avg_sec']}秒）")
    print(f"  AI呼び出し {ai_calls}回・計{ai_sec}秒 → 残りは自社データとルールで処理")
    print(f"  ログ: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

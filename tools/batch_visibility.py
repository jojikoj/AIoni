#!/usr/bin/env python3
"""AI可視性の一括実測 — 企業リスト(CSV)をまとめて測り、結果をJSONに貯める。

用途は2つある。どちらも「AIの鬼」を読ませるメディアから、営業の材料を出す
装置に変えるためのもの。

  1. 業界別ランキング記事の素材（tools/gen_ranking_article.py が使う）
  2. 1社ごとの診断レポート＝アウトバウンドの口実（tools/gen_company_report.py）

判定ロジックは本番の可視性チェッカー(api/diagnose.py)をそのまま読み込んで使う。
コピーすると、片方だけ直したときに「サイトで測った結果」と「営業で出した結果」が
食い違う。客が両方を見比べる前提なので、そこがズレると信用を失う。

── 課金について ───────────────────────────────────────────────
Google検索グラウンディングは、課金済みプロジェクトでも 1,500 リクエスト/日 までは
無料枠（Flash系と共有）。超過分だけ $35/1,000。50社×3票=150リクエストなら
グラウンディング料金は発生せず、実費はトークン分（数十円）だけで済む。
それでも --dry-run で必ず件数を確認してから流すこと。

使い方:
    python3 tools/batch_visibility.py data/companies/fukuoka_kinzoku.csv
    python3 tools/batch_visibility.py <csv> --dry-run          # 件数と費用の試算だけ
    python3 tools/batch_visibility.py <csv> --limit 5          # まず5社で試す
    python3 tools/batch_visibility.py <csv> --votes 3          # 1社あたりの合議回数
    python3 tools/batch_visibility.py <csv> --force            # 測り直す

CSV(UTF-8, ヘッダ必須)の列:
    name      必須。会社名。実測はこの文字列をそのままAIに尋ねる
    url       任意。公式サイト。レポートと突き合わせに使う（実測には渡さない）
    product   任意。主力製品・サービス。入れると同名他社と切り分けやすい
    industry  任意。業界（ランキングの見出しに使う）
    pref      任意。都道府県
    contact   任意。問い合わせフォームのURL（通知メールの下書きに使う）
    note      任意。メモ

APIキー:
    環境変数 GEMINI_API_KEY。無ければ ~/AIoni/.env の同名行を読む。
    本番(Vercel)と同じ課金済みプロジェクトのキーを使うこと。
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))

# 1社あたりの合議回数。本番UIは5回だが、バッチは社数が多く、
# 3回でも判定は一致する（api/diagnose.py の検証記録）。無駄に叩かない。
DEFAULT_VOTES = 3

# 実測1回の目安コスト（円）。入力約1.5k・出力約0.7kトークンを
# Flash-Lite の単価（$0.10/$0.40 per 1M）で見積もり、1ドル=155円で換算。
# グラウンディングは日次1,500件まで無料枠なので、ここには含めない。
YEN_PER_CALL = 0.05
GROUNDING_FREE_PER_DAY = 1500


def _load_env_key() -> str:
    """GEMINI_API_KEY を環境変数→.env の順に探す。"""
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _load_diagnose():
    """api/diagnose.py を「モジュールとして」読み込む。

    api/ はパッケージではなく Vercel の Function 置き場なので通常の import が
    効かない。ファイルパス指定で読む。diagnose.py はモジュール読み込み時に
    副作用（サーバ起動やAPI呼び出し）を持たないので、これで安全に再利用できる。
    """
    path = ROOT / "api" / "diagnose.py"
    spec = importlib.util.spec_from_file_location("aioni_diagnose", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_companies(csv_path: Path) -> list[dict]:
    """CSVを読む。`#` 始まりの行は注記として飛ばす。

    リストの先頭には母集団の出典と取得日を書く決まりにしている
    （data/companies/README.md）。それがヘッダとして読まれないよう、
    DictReader に渡す前にコメント行を落とす。
    """
    rows = []
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        body = [ln for ln in f if not ln.lstrip().startswith("#")]
    for i, row in enumerate(csv.DictReader(body), start=2):
        name = (row.get("name") or "").strip()
        if not name:
            continue
        rows.append({
            "name": name,
            "url": (row.get("url") or "").strip(),
            "product": (row.get("product") or "").strip(),
            "industry": (row.get("industry") or "").strip(),
            "pref": (row.get("pref") or "").strip(),
            "contact": (row.get("contact") or "").strip(),
            "note": (row.get("note") or "").strip(),
            "_line": i,
        })
    return rows


def load_existing(out_path: Path) -> dict:
    if out_path.exists():
        try:
            return json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"⚠ 既存の {out_path.name} が壊れています。新規で作り直します。")
    return {}


def save(out_path: Path, payload: dict) -> None:
    """1社測るごとに書く。途中で落ちても測った分は残す（測り直し＝無駄な課金）。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(out_path)


def measure_one(dg, company: dict, votes: int) -> dict:
    """1社を実測して、本番チェッカーと同じ判定を付けて返す。"""
    body, sources, judge = dg._measure(company["name"], company.get("product", ""), votes=votes)
    level, found, official, third = dg._judge_level(body, sources, judge)
    score = dg._score100(level, judge, official)

    # 情報源はドメイン単位で1件に畳む（同じサイトの別ページが並ぶのを避ける）。
    # uri は vertexaisearch の中継URLで返ることがあり、実ドメインは title 側に入る。
    seen, srcs = set(), []
    for s in sources:
        label = (s.get("title") or "").strip()
        if not label:
            continue
        if label in seen:
            continue
        seen.add(label)
        srcs.append({"title": label, "uri": s.get("uri", ""),
                     "aggregator": bool(dg._is_aggregator(label.lower()))})

    return {
        "name": company["name"],
        "url": company.get("url", ""),
        "product": company.get("product", ""),
        "industry": company.get("industry", ""),
        "pref": company.get("pref", ""),
        "contact": company.get("contact", ""),
        "level": level,
        "score": score,
        "found": found,
        "official": official,
        "third_party": third,
        "judge": judge or {},
        "summary": body,
        "sources": srcs,
        "votes": votes,
        "measured_at": datetime.now(JST).isoformat(timespec="seconds"),
    }


LEVEL_LABEL = {
    0: "同名他社と区別されていない",
    1: "AIに認識されていない",
    2: "第三者の情報だけで語られている",
    3: "公式サイトが根拠になっている",
}


def main() -> int:
    ap = argparse.ArgumentParser(description="企業リストのAI可視性を一括実測する")
    ap.add_argument("csv", help="企業リストCSV（name列必須）")
    ap.add_argument("--out", help="出力JSON（既定: data/visibility/<CSV名>.json）")
    ap.add_argument("--votes", type=int, default=DEFAULT_VOTES, help=f"1社あたりの合議回数（既定 {DEFAULT_VOTES}）")
    ap.add_argument("--limit", type=int, default=0, help="先頭N社だけ測る（試運転用）")
    ap.add_argument("--sleep", type=float, default=1.0, help="1社ごとの待ち秒（既定 1.0）")
    ap.add_argument("--force", action="store_true", help="測定済みも測り直す")
    ap.add_argument("--dry-run", action="store_true", help="APIを叩かず、件数と費用の試算だけ出す")
    args = ap.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.is_absolute():
        csv_path = (ROOT / csv_path) if not csv_path.exists() else csv_path
    if not csv_path.exists():
        print(f"✗ CSVが見つかりません: {csv_path}")
        return 1

    batch = csv_path.stem
    out_path = Path(args.out) if args.out else ROOT / "data" / "visibility" / f"{batch}.json"

    companies = read_companies(csv_path)
    if args.limit:
        companies = companies[: args.limit]
    if not companies:
        print("✗ CSVに有効な行がありません（name列を確認）")
        return 1

    payload = load_existing(out_path)
    done = {r["name"]: r for r in payload.get("results", [])}
    todo = companies if args.force else [c for c in companies if c["name"] not in done]

    calls = len(todo) * args.votes
    print(f"■ バッチ: {batch}")
    print(f"  対象 {len(companies)}社 / 未測定 {len(todo)}社 / 合議 {args.votes}回")
    print(f"  API呼び出し {calls}回  ≒ {calls * YEN_PER_CALL:.0f}円")
    print(f"  検索グラウンディングは日次{GROUNDING_FREE_PER_DAY}件まで無料枠（超過分のみ $35/1000）")
    if calls > GROUNDING_FREE_PER_DAY:
        print(f"  ⚠ 無料枠({GROUNDING_FREE_PER_DAY}件/日)を超えます。--limit で分割してください。")

    if args.dry_run:
        for c in todo[:10]:
            print(f"    - {c['name']}")
        if len(todo) > 10:
            print(f"    … 他 {len(todo) - 10}社")
        return 0
    if not todo:
        print("  すべて測定済みです（測り直すなら --force）")
        return 0

    key = _load_env_key()
    if not key:
        print("✗ GEMINI_API_KEY がありません。")
        print("  本番(Vercel)と同じ課金済みプロジェクトのキーを、次のどちらかに置いてください:")
        print("    export GEMINI_API_KEY=...")
        print(f"    {ROOT}/.env に  GEMINI_API_KEY=...  の1行")
        return 1
    os.environ["GEMINI_API_KEY"] = key

    dg = _load_diagnose()

    results = list(payload.get("results", []))
    if args.force:
        names = {c["name"] for c in todo}
        results = [r for r in results if r["name"] not in names]

    fails = 0
    for i, c in enumerate(todo, start=1):
        label = f"[{i}/{len(todo)}] {c['name']}"
        try:
            r = measure_one(dg, c, args.votes)
        except Exception as e:  # noqa: BLE001 — 種別を問わず1社の失敗で全体を止めない
            fails += 1
            print(f"  ✗ {label} — {e}")
            # 連続で落ちるのは鍵切れ・課金停止・レート超過のいずれか。
            # 叩き続けても直らないので止める（無駄な課金と時間を防ぐ）。
            if fails >= 3:
                print("  ✗ 3社連続で失敗しました。APIキー・課金上限・レート制限を確認してください。")
                break
            continue
        fails = 0
        results.append(r)
        print(f"  ✓ {label} — L{r['level']} {LEVEL_LABEL[r['level']]} ({r['score']}点)")

        payload = {
            "batch": batch,
            "source_csv": str(csv_path.relative_to(ROOT)) if str(csv_path).startswith(str(ROOT)) else str(csv_path),
            "model": dg.MODEL,
            "votes": args.votes,
            "measured_at": datetime.now(JST).isoformat(timespec="seconds"),
            "results": results,
        }
        save(out_path, payload)  # 逐次保存
        if args.sleep:
            time.sleep(args.sleep)

    print(f"\n■ 完了 {len(results)}社 → {out_path}")
    dist = {}
    for r in results:
        dist[r["level"]] = dist.get(r["level"], 0) + 1
    for lv in (3, 2, 1, 0):
        if dist.get(lv):
            print(f"  L{lv} {LEVEL_LABEL[lv]}: {dist[lv]}社")
    return 0


if __name__ == "__main__":
    sys.exit(main())

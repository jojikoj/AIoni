#!/usr/bin/env python3
"""note記事の見出し画像をFluxで生成する。

AIoni/tools/gen_flux_images.py と同じ方針・同じAPIキーを使う。
noteの見出し画像は横長で表示されるため 1280x670（およそ1.91:1）で作る。

実行: python3 gen_note_images.py [記事番号...]   （番号省略で未生成のみ）
"""
from __future__ import annotations
import os, pathlib, sys, time
import requests

OUT = pathlib.Path("/Users/kojimajouji/claude_AIR/TOEcompany/コンテンツ部/案件/AI実践記録/成果物/note/画像")
ENV = pathlib.Path.home() / "claude_AIR/TOEcompany/製作/adobe-integration/.env"
SUBMIT = "https://api.bfl.ai/v1/flux-pro-1.1"

REALISM = ("realistic, professional photograph, candid, natural lighting, "
           "documentary style, avoid AI art, no text, no logos, no watermark")
JAPANESE = "all people in the image are Japanese, in a Japanese workplace setting"

# 記事番号 → 構図。記事の主題を「その仕事の現場」に翻訳する。
# AIっぽい幻想画にしない。文字を写さない。彩度を上げない。
JOBS = {
    "01": "A small business owner standing at a desk counting tally marks on a printed list of routine tasks, morning light through office blinds",
    "02": "A printed comparison table of software options lying face down on a meeting table, a notebook with handwritten notes open beside it",
    "03": "An invoice and a calculator on a desk, a person's hand resting on a stack of unopened supplier documents, quiet office at dusk",
    "04": "A single employee working alone at a small office with three empty desks around, laptop open, late afternoon light",
    "05": "A voice recorder and an open laptop on a meeting room table after a meeting, empty chairs pushed back, natural daylight",
    "06": "A wall-mounted schedule board in a small office showing rows of recurring tasks, someone checking it with a coffee cup in hand, early morning",
    "07": "A person at a desk comparing two laptop screens showing search results, a handwritten tally sheet on paper beside the keyboard, desk lamp at night",
    "08": "Two colleagues reviewing a handwritten scoring sheet together at a meeting table, pen hovering over the rows, plain meeting room",
    "09": "A small server rack in a company back-room, an IT staff member checking cables with a laptop, fluorescent lighting",
    "10": "A help desk worker answering a phone while looking at a chat window on a monitor, small office, natural light",
    "11": "A salesperson typing meeting notes into a laptop in a car parked outside a factory, late afternoon",
    "12": "An accountant checking printed ledgers against a spreadsheet on screen, calculator and red pen on the desk",
    "13": "A hiring manager reading printed resumes at a desk, a stack of applications beside them, plain office, daylight",
    "14": "A person watching an automated process run on a monitor with a hand resting near the keyboard, not touching it, quiet office at night",
}


def api_key() -> str:
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if line.startswith("BFL_API_KEY="):
            v = line.split("=", 1)[1].strip().strip('"').strip("'")
            if v:
                return v
    v = os.environ.get("BFL_API_KEY", "")
    if not v:
        raise SystemExit("BFL_API_KEY が見つかりません")
    return v


def generate(key: str, prompt: str, out: pathlib.Path) -> bool:
    try:
        r = requests.post(SUBMIT,
                          headers={"x-key": key, "Content-Type": "application/json"},
                          json={"prompt": prompt, "width": 1280, "height": 672,
                                "prompt_upsampling": False, "safety_tolerance": 2},
                          timeout=60)
        r.raise_for_status()
        poll = r.json().get("polling_url")
    except Exception as e:
        print(f"  submit失敗: {type(e).__name__}: {e}", file=sys.stderr)
        return False
    if not poll:
        print("  polling_url なし", file=sys.stderr)
        return False

    for _ in range(60):
        time.sleep(2)
        try:
            pr = requests.get(poll, headers={"x-key": key}, timeout=30).json()
        except Exception:
            continue
        st = pr.get("status")
        if st == "Ready":
            url = (pr.get("result") or {}).get("sample")
            if not url:
                return False
            out.write_bytes(requests.get(url, timeout=90).content)
            return True
        if st in ("Error", "Failed", "Content Moderated", "Request Moderated"):
            print(f"  生成失敗: {st}", file=sys.stderr)
            return False
    print("  タイムアウト", file=sys.stderr)
    return False


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    key = api_key()
    targets = sys.argv[1:] or sorted(JOBS)
    ok = 0
    for num in targets:
        if num not in JOBS:
            continue
        dest = OUT / f"{num}.jpg"
        if dest.exists():
            print(f"{num}: 既存（スキップ）")
            ok += 1
            continue
        prompt = f"{JOBS[num]}, {JAPANESE}, {REALISM}"
        print(f"{num}: 生成中…")
        if generate(key, prompt, dest):
            print(f"{num}: OK {dest.stat().st_size // 1024}KB")
            ok += 1
    print(f"完了 {ok}/{len(targets)}")


if __name__ == "__main__":
    main()

"""Flux で AIの鬼 のイメージ写真を生成する。

対象:
  - 画像のないニュース記事に使う、トピック別の汎用フォールバック

方針:
  - 実在の企業・製品・人物を想起させる指示は書かない（誤認を招くため）
  - 近未来的な"AIっぽい"幻想画にしない。実際の仕事場の現場感を出す
  - 記事のサムネイルと並ぶので、彩度を上げすぎない
  - 画面に文字を出さない（英字が写り込むと日本語サイトで浮く）

実行:
    python3 tools/gen_flux_images.py            # 未生成のものだけ作る
    python3 tools/gen_flux_images.py --force    # 全部作り直す
"""
from __future__ import annotations

import base64
import os
import pathlib
import sys
import time

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "img"
ENV = pathlib.Path.home() / "claude_AIR/TOEcompany/製作/adobe-integration/.env"

SUBMIT = "https://api.bfl.ai/v1/flux-pro-1.1"
REALISM = ("realistic, professional photograph, candid, natural lighting, "
           "documentary style, avoid AI art, no text, no logos, no watermark")

# 人物は日本人にする。
# AIの鬼は日本の中小企業向けメディアなので、読者と写真の中の人が
# 一致していないと自分ごとに見えない。
# 指定しないと欧米系の人物が生成されるため、生成時に必ず足す。
#
# ※この縛りは「日本国内向けメディア」限定。UchUchU のように海外へも
#   発信するメディアでは付けないこと（読者が日本人とは限らないため）。
JAPANESE_SUBJECT = ("all people in the image are Japanese, "
                    "in a Japanese workplace setting")

# 人物が写らない構図（机・機材・書類だけ）には付けない
PEOPLE_HINTS = (
    "person", "people", "worker", "employee", "colleague", "developer",
    "engineer", "someone", "hands", "researcher", "technician", "team",
    "doctor", "accountant", "salesperson", "owner", "man", "woman",
    "students", "staff", "clinician", "two ", "three ", "group",
)


def with_japanese_subject(prompt: str) -> str:
    """人物が写るプロンプトなら「日本人」を明示して返す。"""
    low = prompt.lower()
    if "japanese" in low:
        return prompt
    if not any(h in low for h in PEOPLE_HINTS):
        return prompt
    return f"{prompt}, {JAPANESE_SUBJECT}"

JOBS = [
    # --- トピック別フォールバック（画像なし記事に使う）---
    # 同じトピックの記事が並んだときに同じ写真が連続しないよう、
    # 各トピック3枚ずつ用意し、記事のハッシュで振り分ける（build.py）。
    #
    # 方針（指示書 23章）: 「AI企業によくある未来的なサイト」にしない。
    # 青紫グラデ・AI脳のCG・ロボット・意味のない発光表現は避ける。
    # 研究ノート／実験記録／技術編集部の空気を出す。

    # 新モデル
    ("fallback-model-a.jpg",
     "A close-up of a laptop screen showing a plain chat interface in a dim "
     "office at night, a person's hands resting on the keyboard, "
     "shallow depth of field, screen glow as the only light source, " + REALISM),
    ("fallback-model-b.jpg",
     "A developer comparing outputs on two laptops side by side on a desk, "
     "handwritten notes on paper between them, evening office, "
     "warm desk lamp light, " + REALISM),
    ("fallback-model-c.jpg",
     "A quiet meeting room where one person points at a laptop screen while "
     "another takes notes in a notebook, plain white wall behind, "
     "afternoon daylight, " + REALISM),

    # 業務ツール
    ("fallback-tool-a.jpg",
     "An office worker at a tidy desk in a small Japanese company office, "
     "two monitors showing spreadsheets and documents, a notebook and coffee "
     "beside the keyboard, daylight from a window, " + REALISM),
    ("fallback-tool-b.jpg",
     "Hands typing on a keyboard beside a printed checklist and a pen, "
     "a mug and a desk phone at the edge of the frame, plain office desk, "
     "even overhead lighting, " + REALISM),
    ("fallback-tool-c.jpg",
     "A back office in a small company with two employees working at "
     "adjacent desks, filing cabinets and paper trays around, "
     "ordinary fluorescent lighting, documentary feel, " + REALISM),

    # 開発・実装
    ("fallback-dev-a.jpg",
     "Over-the-shoulder view of a software developer working at a desk with "
     "code on two monitors, sticky notes on the monitor edge, "
     "a quiet office in the evening, " + REALISM),
    ("fallback-dev-b.jpg",
     "A whiteboard covered with a hand-drawn system diagram of boxes and "
     "arrows, a marker resting on the tray, an empty chair beside it, "
     "plain meeting room, daylight, " + REALISM),
    ("fallback-dev-c.jpg",
     "A terminal window open on a single monitor on a wooden desk, "
     "a mechanical keyboard and an external drive beside it, "
     "a small potted plant at the edge, natural side light, " + REALISM),

    # 企業動向
    ("fallback-business-a.jpg",
     "Three colleagues in business casual discussing around a meeting table "
     "with a laptop and printed documents, glass partition behind them, "
     "modern Japanese office, natural daylight, candid moment, " + REALISM),
    ("fallback-business-b.jpg",
     "A handshake between two business people at the end of a meeting, "
     "seen from the side at a distance, meeting room table with documents "
     "in the foreground, soft window light, " + REALISM),
    ("fallback-business-c.jpg",
     "An empty modern office lobby with a reception counter and a few chairs, "
     "seen from the entrance, large windows, quiet early morning light, "
     + REALISM),

    # 規制・法制度
    ("fallback-policy-a.jpg",
     "A stack of printed regulatory documents and a pair of reading glasses "
     "on a wooden desk, a laptop half open behind them, "
     "quiet formal office lighting, shallow depth of field, " + REALISM),
    ("fallback-policy-b.jpg",
     "A person reading a thick printed document at a desk, marking a passage "
     "with a highlighter, only the hands and papers in frame, "
     "neutral desk lighting, " + REALISM),
    ("fallback-policy-c.jpg",
     "The facade of a plain government office building seen from street "
     "level on an overcast day, no signage legible, " + REALISM),

    # 研究動向
    ("fallback-research-a.jpg",
     "A university researcher writing equations on a whiteboard in a "
     "seminar room, partially filled board, chairs visible at the frame edge, "
     "even daylight from tall windows, " + REALISM),
    ("fallback-research-b.jpg",
     "A desk in a research lab with an open laptop showing a line chart, "
     "a printed paper with graphs beside it, a coffee cup and pens, "
     "cool daylight, " + REALISM),
    ("fallback-research-c.jpg",
     "A quiet university library reading area with a laptop and stacked "
     "books on a long wooden table, empty chairs around, "
     "afternoon light through windows, " + REALISM),

    # 半導体・インフラ
    ("fallback-infra-a.jpg",
     "A long aisle inside a data center between rows of server racks, "
     "cable trays overhead, cool blue indicator lights, a technician small "
     "in the far distance for scale, wide shot, " + REALISM),
    ("fallback-infra-b.jpg",
     "Close-up of structured network cabling patched into a switch panel "
     "inside a server rack, neatly bundled cables, small status lights, "
     "cool ambient lighting, " + REALISM),
    ("fallback-infra-c.jpg",
     "An electrical substation and cooling units on the roof of a large "
     "industrial building, seen against an overcast sky, "
     "flat neutral daylight, " + REALISM),

    # 国内動向
    ("fallback-japan-a.jpg",
     "A small Japanese office interior seen from the entrance, several desks "
     "with monitors, a whiteboard on the wall, employees working, "
     "warm afternoon daylight through blinds, " + REALISM),
    ("fallback-japan-b.jpg",
     "A Japanese business district street in the morning with office workers "
     "walking, mid-rise buildings, seen from across the street, "
     "overcast flat light, " + REALISM),
    ("fallback-japan-c.jpg",
     "The interior of a small Japanese factory office with a desk, a "
     "computer, production schedules pinned to the wall, and a window "
     "looking onto the workshop floor, natural light, " + REALISM),

    # 分類なし
    ("fallback-default-a.jpg",
     "A person working alone at a desk with a laptop in a quiet office, "
     "seen from the side at a distance, window light, calm neutral tones, "
     + REALISM),
    ("fallback-default-b.jpg",
     "An empty desk with a closed laptop, a notebook and a pen, "
     "seen from directly above, plain wooden surface, soft even light, "
     + REALISM),
    ("fallback-default-c.jpg",
     "A quiet open-plan office seen from the back, a few people working at "
     "distant desks, ceiling lights on, ordinary working afternoon, "
     + REALISM),
]


def api_key() -> str:
    if ENV.exists():
        for line in ENV.read_text(encoding="utf-8").splitlines():
            if line.startswith("BFL_API_KEY="):
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                if v:
                    return v
    v = os.environ.get("BFL_API_KEY", "")
    if not v:
        print("BFL_API_KEY が見つかりません", file=sys.stderr)
        raise SystemExit(1)
    return v


def generate(key: str, prompt: str, out: pathlib.Path) -> bool:
    """1枚生成する。submit → polling_url をポーリングして取得する。"""
    try:
        r = requests.post(
            SUBMIT,
            headers={"x-key": key, "Content-Type": "application/json"},
            json={"prompt": prompt, "width": 1024, "height": 576,
                  "prompt_upsampling": False, "safety_tolerance": 2},
            timeout=60)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print(f"  submit失敗: {type(e).__name__}: {e}", file=sys.stderr)
        return False

    # レスポンスの polling_url を使う（id からURLを組み立てない）
    poll = data.get("polling_url")
    if not poll:
        print(f"  polling_url なし: {data}", file=sys.stderr)
        return False

    for _ in range(60):
        time.sleep(2)
        try:
            pr = requests.get(poll, headers={"x-key": key}, timeout=30).json()
        except Exception:
            continue
        status = pr.get("status")
        if status == "Ready":
            url = (pr.get("result") or {}).get("sample")
            if not url:
                return False
            img = requests.get(url, timeout=90).content
            out.write_bytes(img)
            return True
        if status in ("Error", "Failed", "Content Moderated",
                      "Request Moderated"):
            print(f"  生成失敗: {status}", file=sys.stderr)
            return False
    print("  タイムアウト", file=sys.stderr)
    return False


def article_jobs() -> list[tuple[str, str]]:
    """オリジナル記事の front matter から hero / image_prompt を集める。

    fallback と違ってジョブをここに書かない。記事側の front matter が正。
    記事を足せば、次の実行で自動的にその1枚だけが生成される。
    """
    jobs: list[tuple[str, str]] = []
    art_dir = ROOT / "content" / "articles"
    if not art_dir.exists():
        return jobs
    for md in sorted(art_dir.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        fm = text.split("---", 2)[1]
        hero = prompt = ""
        for line in fm.splitlines():
            if line.startswith("hero:"):
                hero = line.split(":", 1)[1].strip()
            elif line.startswith("image_prompt:"):
                prompt = line.split(":", 1)[1].strip()
        if not hero:
            continue
        if not prompt:
            print(f"  ⚠️ image_prompt なし: {md.name}", file=sys.stderr)
            continue
        # 記事側で毎回書き忘れないよう、写実指定はここで必ず足す
        if "realistic" not in prompt:
            prompt = f"{prompt}, {REALISM}"
        jobs.append((hero, with_japanese_subject(prompt)))
    return jobs


def run(key: str, jobs: list[tuple[str, str]], force: bool) -> tuple[int, int, int]:
    ok = skip = fail = 0
    for name, prompt in jobs:
        path = OUT / name
        if path.exists() and not force:
            print(f"skip  {name}（既存）")
            skip += 1
            continue
        print(f"生成中 {name} ...")
        if generate(key, prompt, path):
            print(f"  ✅ {path.stat().st_size // 1024}KB")
            ok += 1
        else:
            fail += 1
    return ok, skip, fail


def main() -> int:
    force = "--force" in sys.argv
    only_articles = "--articles" in sys.argv
    only_fallback = "--fallback" in sys.argv

    key = api_key()
    OUT.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[str, str]] = []
    if not only_articles:
        jobs += [(n, with_japanese_subject(p)) for n, p in JOBS]
    if not only_fallback:
        arts = article_jobs()
        print(f"記事hero: {len(arts)}件を対象にします")
        jobs += arts

    ok, skip, fail = run(key, jobs, force)
    print(f"\n=== 生成{ok} / スキップ{skip} / 失敗{fail} ===")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

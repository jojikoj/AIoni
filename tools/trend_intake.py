#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AIの鬼｜旬ネタ取り込み（提案キュー方式）。

方針: AIの鬼は「実測ラボ」。実測記事は捏造禁止・人が書く（自動生成しない）。
そこで旬は“自動公開”ではなく“提案”として供給する。
「いま検索/世間で伸びているAI話題 × まだ自分が書いていないもの」を並べ、
中の鬼(とがった読み物) / 実践室(実測ネタ) / 解説 の当てはめ候補を出す。
どれを書くかは人が決める（ラボの純度＝勝ち筋）。

出力: AIoni/_旬ネタ/提案_<なし日付>.md （content/articles外なので公開されない）
  python3 tools/trend_intake.py
"""
from __future__ import annotations
import sys, pathlib, re

ROOT = pathlib.Path(__file__).resolve().parent.parent
SHARED = pathlib.Path.home() / "claude_AIR/TOEcompany/メディア事業部/共通/旬ネタ"
sys.path.insert(0, str(SHARED))
from topic_picker import fresh_topics          # noqa: E402
from trend_signals import trends_matching       # noqa: E402

SEEDS = ["ChatGPT 使い方", "Claude 新モデル", "Gemini 最新", "AI エージェント",
         "生成AI 業務", "AI 中小企業", "AI 実測", "プロンプト コツ",
         "AI 議事録", "AI 検索", "ローカルLLM", "AI 失敗"]
THEME_KW = ["ai", "chatgpt", "claude", "gemini", "llm", "生成ai", "プロンプト",
            "エージェント", "モデル", "gpt", "grok", "深層学習", "機械学習"]


def _existing_titles() -> list[str]:
    out = []
    for md in (ROOT / "content" / "articles").glob("*.md"):
        m = re.search(r"^title:\s*(.+)$", md.read_text(encoding="utf-8"), re.M)
        if m:
            out.append(m.group(1).strip())
    return out


def _corner(query: str) -> str:
    if any(w in query for w in ("失敗", "使い方", "コツ", "議事録", "実測", "中小企業", "業務")):
        return "実践室(実測ネタ)"
    if any(w in query for w in ("とは", "違い", "比較", "できる", "料金", "最新", "いつ", "新モデル", "ニュース", "アップデート")):
        return "解説"
    return "中の鬼(とがった読み物)"


def _dedupe_core(cands: list[dict]) -> list[dict]:
    """「gemini 最新○○」のような近似重複を、先頭2語で1本に圧縮。"""
    seen, out = set(), []
    for c in cands:
        core = c["query"].replace(" ", "")[:8]   # 先頭8文字が同じ＝ほぼ同一話題
        if core in seen:
            continue
        seen.add(core)
        out.append(c)
    return out


def main() -> int:
    existing = _existing_titles()
    cands = _dedupe_core(fresh_topics(SEEDS, THEME_KW, existing, limit=40))[:12]
    hot = trends_matching(THEME_KW)   # 世間の旬とAIが重なった話題（あれば強い）

    out = pathlib.Path(ROOT / "_旬ネタ" / "提案.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# AIの鬼 旬ネタ提案（自動抽出・人が選ぶ）", "",
             "> 実測は捏造禁止・人が書く。ここは“旬×AI×未カバー”の候補出しまで。", ""]
    if hot:
        lines += ["## 🔥 世間の旬とAIが重なっている話題（最優先で拾う）"]
        lines += [f"- {h}" for h in hot] + [""]
    lines += ["## 旬の検索ネタ（コーナー当てはめ案）", "",
              "| 旬度 | 検索フレーズ | 当てはめ先 |", "|---|---|---|"]
    for c in cands:
        lines.append(f"| {'🔥'*c['score'] or '·'} | {c['query']} | {_corner(c['query'])} |")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[trend_intake] 候補{len(cands)} / 旬×AI一致{len(hot)} → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

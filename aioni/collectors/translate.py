"""翻訳エンジン（3段フォールバック）。

外部の従量課金APIは使わない。優先順位:

  1. claude CLI  … ローカルの Claude Code を叩く。品質が最も高い。
                   API従量課金ではなく Claude Code の契約枠で動く。
                   Mac 上での収集（cron / run.sh）ではこれが使われる。
  2. argostranslate … 完全オフラインの機械翻訳。claude CLI が無い環境
                   （GitHub Actions 等）でのフォールバック。品質は劣る。
  3. 翻訳なし    … どちらも無ければ原文のまま掲載する（サイトは常に動く）。

日→英は argostranslate の品質が公開に耐えないため、
argostranslate 使用時は英→日のみ行う（呼び出し側で制御）。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys

# --- 前処理: 訳文を汚すRSS定型文を落とす -------------------------------
_BOILERPLATE = [
    re.compile(r"The post\b.*?appeared first on.*?(?:\.|$)", re.I | re.S),
    re.compile(r"Read this release in English here\.?", re.I),
    re.compile(r"^\s*(?:Description|CONTRACT RELEASE|MEDIA ADVISORY|RELEASE)\s*[:\-]?\s*", re.I),
    re.compile(r"\[\s*(?:…|\.\.\.)\s*\]"),
    re.compile(r"Continue reading.*?(?:\.|$)", re.I),
    re.compile(r"\bClick here\b.*?(?:\.|$)", re.I),
]


def clean_for_translation(text: str) -> str:
    if not text:
        return ""
    out = text
    for pat in _BOILERPLATE:
        out = pat.sub(" ", out)
    return re.sub(r"\s+", " ", out).strip()


# =====================================================================
#  バックエンド 1: claude CLI
# =====================================================================
CLAUDE_BIN = os.environ.get("AIONI_CLAUDE_BIN") or shutil.which("claude")
CLAUDE_BATCH = 12          # 1回のプロンプトに載せる記事数
CLAUDE_TIMEOUT = 240       # 秒

# 翻訳に使うモデル。数百件の定型処理なので軽量モデルで足りる。
# 上位モデルを使うと利用枠を圧迫し、対話側が止まる。
BATCH_MODEL = os.environ.get("AIONI_BATCH_MODEL", "haiku")

_PROMPT = """あなたはAI・ソフトウェア分野の専門翻訳者です。
以下のJSONは英語のAI関連ニュースです。各記事の title と summary を、
日本語のニュース記事として自然な文体に翻訳してください。

要件:
- title は日本語の報道見出しらしく簡潔に（体言止め・「〜を発表」等を活用）
- summary は敬体（です・ます）ではなく常体（だ・である）に寄せた報道文
- 製品名・モデル名・企業名は原綴りのまま残す（例: GPT-5, Claude, Gemini, Hugging Face）
  カタカナに開かない。日本で定着した表記がある場合のみそれに従う（例: OpenAI→OpenAI）
- 技術用語は定訳を使う（fine-tuning→ファインチューニング、inference→推論、
  benchmark→ベンチマーク、open-weight→オープンウェイト、context window→コンテキスト長）
- 訳しにくい専門用語は無理に和訳せず原語のまま残す方がよい
- 原文にない情報を足さない。誇張しない。
- 出力は入力と同じキー構造のJSONのみ。前置き・説明・コードフェンスは一切書かない。

入力:
"""


def claude_available() -> bool:
    return bool(CLAUDE_BIN)


def _extract_json(text: str) -> dict | None:
    """CLI出力からJSONオブジェクトを取り出す。"""
    if not text:
        return None
    text = text.strip()
    # コードフェンスが付いた場合を剥がす
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


def _claude_call(payload: dict) -> dict | None:
    prompt = _PROMPT + json.dumps(payload, ensure_ascii=False, indent=1)
    try:
        proc = subprocess.run(
            [CLAUDE_BIN, "--model", BATCH_MODEL, "-p", prompt],
            capture_output=True, text=True, timeout=CLAUDE_TIMEOUT,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"    [claude] 呼び出し失敗: {type(e).__name__}", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(f"    [claude] exit={proc.returncode}: {proc.stderr[:200]}", file=sys.stderr)
        return None
    return _extract_json(proc.stdout)


def translate_items_claude(items: list[dict]) -> int:
    """英語記事リストに title_ja / summary_ja を付与する。付与できた件数を返す。"""
    if not claude_available() or not items:
        return 0
    filled = 0
    for i in range(0, len(items), CLAUDE_BATCH):
        chunk = items[i:i + CLAUDE_BATCH]
        payload = {
            str(n): {
                "title": clean_for_translation(it.get("title", "")),
                "summary": clean_for_translation(it.get("summary", "")),
            }
            for n, it in enumerate(chunk)
        }
        result = _claude_call(payload)
        if not result:
            print(f"    [claude] batch {i // CLAUDE_BATCH + 1} 失敗 — フォールバックへ", file=sys.stderr)
            continue
        for n, it in enumerate(chunk):
            got = result.get(str(n))
            if not isinstance(got, dict):
                continue
            title = (got.get("title") or "").strip()
            summary = (got.get("summary") or "").strip()
            if title:
                # 元要約が字数で切り詰められている場合、訳文も途中で終わるため
                # 省略記号を補って「続きがある」ことを示す。
                if summary and it.get("summary", "").rstrip().endswith("…") \
                        and not summary.endswith(("…", "。", "！", "？")):
                    summary = summary.rstrip("、,.") + "…"
                it["title_ja"] = title
                it["summary_ja"] = summary or it.get("summary_ja") or ""
                it["translated_ja"] = True
                filled += 1
        print(f"    [claude] {min(i + CLAUDE_BATCH, len(items))}/{len(items)} 翻訳済み")
    return filled


# =====================================================================
#  バックエンド 2: argostranslate（完全オフライン）
# =====================================================================
_ENGINE = None
_CHECKED = False

# 機械翻訳が定型的に外す語だけを狙って直す
_GLOSSARY_JA = [
    (re.compile(r"大規模言語モデル\s*\(LLM\)"), "大規模言語モデル"),
    (re.compile(r"微調整"), "ファインチューニング"),
    (re.compile(r"埋め込みベクトル?"), "埋め込み"),
    (re.compile(r"文脈ウィンドウ"), "コンテキスト長"),
    (re.compile(r"幻覚(?=を|が|の|し)"), "ハルシネーション"),
    (re.compile(r"オープンソースの重み"), "オープンウェイト"),
    (re.compile(r"変圧器モデル"), "Transformer"),
    (re.compile(r"拡散モデル"), "拡散モデル"),
    (re.compile(r"推論時間"), "推論"),
    (re.compile(r"\s*(?:ログイン|投稿|コンテンツ)\s*$"), ""),
    (re.compile(r"^\s*(?:ログイン|投稿|コンテンツ)\s*"), ""),
]


def polish_ja(text: str) -> str:
    if not text:
        return text
    out = text
    for pat, rep in _GLOSSARY_JA:
        out = pat.sub(rep, out)
    return re.sub(r"\s+", " ", out).strip()


def _load_engine():
    global _ENGINE, _CHECKED
    if _CHECKED:
        return _ENGINE
    _CHECKED = True
    try:
        import argostranslate.translate as t
        _ENGINE = t
    except Exception:
        _ENGINE = None
    return _ENGINE


def argos_available() -> bool:
    return _load_engine() is not None


def translate(text: str, from_lang: str, to_lang: str) -> str | None:
    """argostranslate による単文翻訳。未導入・失敗時は None。"""
    if not text or from_lang == to_lang:
        return text or None
    engine = _load_engine()
    if engine is None:
        return None
    src = clean_for_translation(text)
    if not src:
        return None
    try:
        out = engine.translate(src, from_lang, to_lang)
    except Exception:
        return None
    if not out:
        return None
    if to_lang == "ja":
        out = polish_ja(out)
    return out or None


def translate_items_argos(items: list[dict]) -> int:
    """英語記事に title_ja / summary_ja を付ける（オフライン・低品質）。"""
    if not argos_available():
        return 0
    filled = 0
    total = len(items)
    for n, it in enumerate(items, 1):
        title = translate(it.get("title", ""), "en", "ja")
        if title:
            it["title_ja"] = title
            summary = translate(it.get("summary", ""), "en", "ja")
            if summary:
                it["summary_ja"] = summary
            it["translated_ja"] = True
            filled += 1
        if n % 10 == 0 or n == total:
            print(f"    [argos] {n}/{total} 翻訳済み")
    return filled


# =====================================================================
#  公開API
# =====================================================================
def available() -> bool:
    return claude_available() or argos_available()


def backend_name() -> str:
    if claude_available():
        return "claude CLI"
    if argos_available():
        return "argostranslate (offline)"
    return "none"


def translate_english_items(items: list[dict]) -> int:
    """英語記事を日本語化する。使えるバックエンドを順に試す。"""
    if not items:
        return 0
    if claude_available():
        filled = translate_items_claude(items)
        # claude が一部失敗した分だけ argos で埋める
        remaining = [it for it in items if not it.get("translated_ja")]
        if remaining and argos_available():
            print(f"    未翻訳 {len(remaining)}件を argostranslate で補完")
            filled += translate_items_argos(remaining)
        return filled
    return translate_items_argos(items)


def install_models():
    """argostranslate の英⇄日モデルを導入する。"""
    import argostranslate.package as pkg
    pkg.update_package_index()
    wanted = {("en", "ja"), ("ja", "en")}
    installed = 0
    for p in pkg.get_available_packages():
        if (p.from_code, p.to_code) in wanted:
            print(f"installing {p.from_code}->{p.to_code} ...")
            pkg.install_from_path(p.download())
            installed += 1
    print(f"done. installed {installed} model(s).")


if __name__ == "__main__":
    if "--install" in sys.argv:
        install_models()
    else:
        print("backend:", backend_name())
        print("  claude CLI    :", claude_available(), CLAUDE_BIN or "")
        print("  argostranslate:", argos_available())

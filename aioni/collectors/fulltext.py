"""元記事の本文を取得し、独自の日本語要約を作る。

RSSが配信する要約は50〜150字程度で、しかも途中で切れていることが多い。
それだけを載せた記事ページは読者にとって価値がなく、
検索エンジンからも「中身の薄いページ」と見なされる。

そこで元記事の本文を取得し、**120〜200字の日本語要約**を生成する。

短くするのは意図的。長い要約を大量生成すると
(1) 引用の範囲を超えて元記事の代替物になり、
(2) 大量生成コンテンツと見なされてサイト全体の評価を落とす。
集約は「元記事に行くかどうかを判断できる材料」までにとどめる。
本文そのものは保存も掲載もしない（著作権は元の発信者にあるため）。
生成するのは要約であって転載ではない。

守っていること:
  - robots.txt を必ず確認し、拒否されているサイトは取得しない
  - User-Agent に連絡先を含め、身元を明示する
  - リクエスト間隔を空け、相手サーバーに負荷をかけない
  - 本文は要約生成にのみ使い、保存しない
  - 掲載時は必ず出典と元記事リンクを併記する
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse as up
import urllib.robotparser as rp

import requests

from .. import config
from . import translate

try:
    import trafilatura
except ImportError:
    trafilatura = None

UA = "AIoni/1.0 (+https://github.com/; AI news aggregator)"
FETCH_TIMEOUT = 20
POLITE_INTERVAL = 1.5      # 同一ホストへの連続アクセス間隔（秒）
MIN_BODY = 400             # これ未満なら要約に足る本文が取れていないと判断
TARGET_CHARS = 120         # 生成する要約の最低文字数（上限は200字）

# 要約生成に使うモデル。数百件を回す定型処理なので軽量モデルを指定する。
# 指定しないとCLIの既定モデル（＝対話と同じ上位モデル）が使われ、
# 利用枠を食い潰して途中から全件失敗する。実際に414件が失敗した。
BATCH_MODEL = os.environ.get("AIONI_BATCH_MODEL", "haiku")

_robots_cache: dict[str, rp.RobotFileParser | None] = {}
_last_access: dict[str, float] = {}


def _allowed(url: str) -> bool:
    """robots.txt で許可されているかを確認する。判断できない場合は取得しない。"""
    host = up.urlparse(url).netloc
    if host not in _robots_cache:
        parser = rp.RobotFileParser()
        parser.set_url(f"https://{host}/robots.txt")
        try:
            parser.read()
            _robots_cache[host] = parser
        except Exception:
            _robots_cache[host] = None
    parser = _robots_cache[host]
    if parser is None:
        return False          # 確認できないなら取りに行かない
    try:
        return parser.can_fetch(UA, url)
    except Exception:
        return False


def _wait(host: str) -> None:
    last = _last_access.get(host, 0.0)
    delta = time.time() - last
    if delta < POLITE_INTERVAL:
        time.sleep(POLITE_INTERVAL - delta)
    _last_access[host] = time.time()


def fetch_body(url: str) -> str:
    """元記事の本文を返す。取得できない場合は空文字。"""
    if trafilatura is None or not url:
        return ""
    if not _allowed(url):
        return ""
    host = up.urlparse(url).netloc
    _wait(host)
    try:
        r = requests.get(url, timeout=FETCH_TIMEOUT, headers={"User-Agent": UA})
        r.raise_for_status()
    except Exception:
        return ""
    try:
        text = trafilatura.extract(
            r.text, include_comments=False, include_tables=False,
            no_fallback=False) or ""
    except Exception:
        return ""
    return text.strip()


# --- 要約生成 -----------------------------------------------------------
_PROMPT = """あなたはAI分野の専門メディアの編集者です。
読者は中小企業の経営者・情報システム担当で、研究者ではありません。
以下の記事本文を読み、日本語で**短い要約**を書いてください。

これは元記事の代わりではなく、**読者が「元記事を読むかどうか」を判断するための材料**です。
記事の内容を再現しようとしないでください。

要件:
- **120〜200字**。これを超えないこと
- 1段落。改行しない
- 「何が起きたか」を1文目で述べる
- 2文目以降で、中小企業に関係する点があれば一言そえる（無ければ書かない）
- 製品名・モデル名・企業名は原綴りのまま（例: GPT-5, Claude, Hugging Face）
- 原文にない事実を足さない。推測を断定で書かない
- 敬体（です・ます）ではなく常体（だ・である）
- 出力は要約本文のみ。前置き・説明・引用符・見出しは書かない

記事タイトル: {title}

記事本文:
{body}
"""


def summarize(title: str, body: str) -> str:
    """本文から120〜200字の日本語要約を生成する。失敗時は空文字。"""
    if not body or len(body) < MIN_BODY:
        return ""
    if not translate.claude_available():
        return ""
    # 長すぎる本文は先頭を使う（結論が先に書かれる記事が多いため）
    src = body[:6000]
    prompt = _PROMPT.format(title=title, body=src)
    import subprocess
    try:
        proc = subprocess.run(
            [translate.CLAUDE_BIN, "--model", BATCH_MODEL, "-p", prompt],
            capture_output=True, text=True, timeout=300)
    except Exception as e:
        print(f"    [summary] 呼び出し失敗: {type(e).__name__}", file=sys.stderr)
        return ""
    if proc.returncode != 0:
        return ""
    out = proc.stdout.strip()
    # コードフェンスが付いた場合は剥がす
    if out.startswith("```"):
        out = out.split("```")[1] if "```" in out[3:] else out
        out = out.lstrip("markdown").lstrip("\n")
    return out.strip()


def enrich(items: list[dict], limit: int | None = None,
           save_cb=None, save_every: int = 5) -> int:
    """記事に本文由来の要約（body_ja）を付与する。付与できた件数を返す。

    既に body_ja がある記事はスキップするため、
    再実行しても新着分だけが処理される。

    全件で数時間かかるため、save_every 件ごとに save_cb を呼んで
    途中経過を保存する。中断しても、そこまでの成果は失われない。
    """
    targets = [it for it in items if not it.get("body_ja") and it.get("url")]
    if limit:
        targets = targets[:limit]
    if not targets:
        print("  [fulltext] 新規対象なし")
        return 0

    print(f"  [fulltext] 本文取得＋要約生成: {len(targets)}件")
    done = skipped = 0
    # 要約生成が連続で失敗する場合、claude CLI 側が使えなくなっている
    # 可能性が高い。空振りを続けても意味がないので打ち切る。
    consecutive_fail = 0
    for i, it in enumerate(targets, 1):
        body = fetch_body(it["url"])
        if not body or len(body) < MIN_BODY:
            it["body_skip"] = "no_body"
            skipped += 1
        else:
            summary = summarize(it.get("title", ""), body)
            if summary and len(summary) >= 300:
                it["body_ja"] = summary
                it["body_chars"] = len(summary)
                done += 1
                consecutive_fail = 0
            else:
                # 一時的な失敗と恒久的な失敗を区別できないため、
                # フラグは付けずに次回の再試行対象として残す
                skipped += 1
                consecutive_fail += 1
                if consecutive_fail >= 8:
                    print("    要約生成が8件連続で失敗。"
                          "利用上限に達した可能性が高いため中断する。",
                          file=sys.stderr)
                    if save_cb:
                        save_cb()
                    return done
        # 途中経過を保存する（4時間かかる処理を最後まで抱え込まない）
        if save_cb and (i % save_every == 0 or i == len(targets)):
            save_cb()
        if i % 10 == 0 or i == len(targets):
            print(f"    {i}/{len(targets)}  生成{done} / スキップ{skipped}", flush=True)
    return done


def main() -> int:
    path = config.DATA_DIR / "news.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    limit = None
    for a in sys.argv[1:]:
        if a.startswith("--limit="):
            limit = int(a.split("=", 1)[1])
    def save():
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)   # 書き込み中の破損を避けるため原子的に置き換える

    n = enrich(data["items"], limit=limit, save_cb=save)
    save()
    total = sum(1 for x in data["items"] if x.get("body_ja"))
    print(f"=== 今回 {n}件生成 / 累計 {total}件が本文要約つき ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

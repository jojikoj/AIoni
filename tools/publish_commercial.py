"""仕事につながる検索語に対して、当社の実測だけで記事を1本書く。

なぜ作ったか（2026-08-16）:
    実測で、当社が表示を得ている語のうち相談につながるのはこの型だった。

      aiエージェント 総務 … 19表示 最高61位 クリック0
      ai研修 法人 選定   …  9表示 最高92位 クリック0
      生成ai 開発会社    …  8表示 最高69位 クリック0
      ai開発 見積もり 費用 内訳 … 2表示 最高100位 クリック0

    順位が低くても表示が出ている＝その語を検索する人が実在し、Google が
    当社を候補として認識している。ここは「書けば取れる余地のある需要」。

    当初は「一般論では大手に勝てないので、ここは人が一次情報で書く」と
    設計していたが、**今後も人は記事を書かない**方針が確定した（小嶋さん）。
    そこで、当社が実際に測った数字だけを素材にして自動で書く。
    一次情報が無い語は書かない——一般論で埋めると、このサイトの前提
    （実測しか書かない）が壊れるため。書けない日は書かないでよい。

publish_daily.py との違い:
    publish_daily … その日のニュースが題材。旬で勝負する。毎日。
    ここ          … 検索需要が題材。素材は当社の実測。週2回（火・金）。

    どちらも捏造ガードは同じ（FACTSと素材に無い数字は不合格）。

実行:
    python3 tools/publish_commercial.py            # 1本公開
    python3 tools/publish_commercial.py --dry-run  # 生成と検査だけ
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from publish_daily import (FACTS, AUTHOR, gen_with_claude, strip_fence,  # noqa: E402
                           inspect, log, auto_facts)

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "content" / "articles"
QUERIES = ROOT / "data" / "gsc_queries.json"
HISTORY = ROOT / "data" / "gsc_history.tsv"
STATS = ROOT / "data" / "daily_stats.tsv"
REJECTED = ROOT / "content" / "_aeo_rejected"
# どの語で書いたかの記録。同じ語を何度も書かないため。
WRITTEN = ROOT / "data" / "commercial_written.json"

TAG = "AI仕事術"          # 中小企業がAIを実務に入れるための実践ガイドの棚
MIN_CHARS = 2000
MAX_TRIES = 4            # 1本通るまでに試す検索語の数


def written() -> dict:
    if WRITTEN.exists():
        try:
            return json.loads(WRITTEN.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def candidates() -> list[dict]:
    """まだ書いていない商用クエリを、需要の大きい順に返す。"""
    if not QUERIES.exists():
        log("⚠️ data/gsc_queries.json が無い（先に daily_review.py を回すこと）")
        return []
    d = json.loads(QUERIES.read_text(encoding="utf-8"))
    done = written()
    out = []
    for a in d.get("commercial", []):
        if a["q"] in done:
            continue
        # その語で自社記事が既に表示されているなら、新規を書くと共食いになる。
        # 実測でニュース要約ページが自社記事の前に立つ型を1,187ページ分
        # 片付けたばかりで、今度は自社記事どうしで同じことをやる意味がない。
        # 既存がある語は加筆で戦う（reinforce_targets に回す）。
        if a.get("has_article"):
            continue
        out.append(a)
    return out


def reinforce_targets() -> list[dict]:
    """既に自社記事が立っている商用クエリ。新規ではなく加筆で戦う対象。"""
    if not QUERIES.exists():
        return []
    d = json.loads(QUERIES.read_text(encoding="utf-8"))
    return [a for a in d.get("commercial", []) if a.get("has_article")]


def own_metrics() -> str:
    """AIの鬼自身の運用実測。これも当社の一次情報として使える。"""
    lines = []
    if HISTORY.exists():
        rows = [l.split("\t") for l in
                HISTORY.read_text(encoding="utf-8").splitlines()[1:]]
        if len(rows) >= 7:
            cur = rows[-7:]
            imp = sum(int(r[1]) for r in cur)
            clk = sum(int(r[2]) for r in cur)
            lines.append(f"- 当サイトの直近7日（{cur[0][0]}〜{cur[-1][0]}）: "
                         f"検索表示{imp}回・クリック{clk}回")
    if STATS.exists():
        last = STATS.read_text(encoding="utf-8").splitlines()[-1].split("\t")
        if len(last) >= 5:
            lines.append(f"- {last[0]}時点の当サイト: {last[1]}・{last[2]}・"
                         f"{last[4]}（自動収集と自動生成の実績）")
    n = len(list(ARTICLES.glob("*.ja.md")))
    lines.append(f"- 当サイトの記事本数: {n}本（うち大半は自動生成）")
    return "\n".join(lines)


def link_pool(slugs: set[str], query: str) -> list[tuple[str, str]]:
    """張り先。その語に関係しそうな既存記事を優先する。"""
    words = [w for w in re.split(r"[\s　]+", query) if len(w) >= 2]
    scored = []
    for p in sorted(ARTICLES.glob("*.ja.md")):
        t = p.read_text(encoding="utf-8")
        m = re.search(r"^title: (.+)$", t, re.M)
        title = m.group(1).strip() if m else ""
        score = sum(1 for w in words if w in title or w in t[:2000])
        scored.append((score, p.name[: -len(".ja.md")], title))
    scored.sort(key=lambda z: -z[0])
    return [(s, t) for _, s, t in scored[:12]]


def build_prompt(q: dict, links: list[tuple[str, str]], today: str) -> str:
    link_lines = "\n".join(f"- ../{s}/ … {t}" for s, t in links)
    return f"""あなたは「AIの鬼」（ai-oni.com、株式会社TOEが運営する中小企業向けの
AI実践・実測メディア）の編集部です。読者は中小企業の経営者・情報システム担当です。

# 今回のお題

読者が実際に検索している言葉: **{q['q']}**
（直近28日で当サイトが{q['imp']}回表示され、最高{q['pos']}位。つまりこの語を
 打ち込む人は実在するが、当社の記事は読まれる位置にいない）

この語で検索した人が求めている答えを、**当社が実際に測った数字だけ**で書いてください。

# 最重要（ここを外したら書かない方がまし）

- **素材に無い数字・事実は一切書かない。** 「一般的には」「多くの企業では」
  「相場は〜と言われています」は全部禁止。それは検索すれば出てくる一般論で、
  大手メディアに勝てないうえ、このサイトの前提（実測しか書かない）が壊れます。
- **素材で答えられないなら、書かないでください。** その場合は本文を書かず
  `SKIP: 理由` の1行だけを返してください。1本落ちても構いません。
  裏の取れない記事を出す方が損失です。
- 分からないことは「当社では測っていません」と正直に書く。
- 株式会社TOEはAI導入支援を売る利害関係者だと明示する。
- 効果や成果を保証しない。
- 実在しない事例・顧客・受賞・製品名を作らない。会社名は「〇〇工業株式会社」と伏せる。
- 文体は敬体（です・ます）。

# 書き方

- 冒頭200字以内で結論を言い切る。検索した人がその場で答えを得られるように。
- **検索語「{q['q']}」をタイトルと本文にそのまま使う**（言い換えない）。
- 具体で書く。固有名詞・数値・条件・日付を落とさない。
  「大幅に」「多くの」に置き換えない。
- 当社が測っていない部分は、測っていないと書いたうえで
  「では何なら分かるのか」を示す。そこが読者の役に立つ部分です。

# 記事の型（すべて満たすこと）

1. 1行目から `---` で囲んだフロントマター。項目は
   slug / title / excerpt / tag / author / date / hero / image_prompt / order
   - slug: 英小文字とハイフンのみ（6〜60字）。日付や連番を入れない
   - title: 検索語をそのまま含める。問いの形にする
   - excerpt: 120〜200字。結論を先に
   - tag: {TAG}
   - author: {AUTHOR}
   - date: {today}
   - hero: article-<slug>.jpg
   - image_prompt: 英語1行。日本人が写る明るい実写写真の指示。late morning /
     bright daylight / カメラとレンズ / 生活痕を入れ、末尾は
     "unretouched documentary photograph, realistic, plain unmarked surfaces,
     no text, no logos, no signage" で終える
   - order: 30
2. `##` の見出しを4本以上。
3. **Markdownの表を必ず1つ以上入れる。** これは必須で、無いと不合格です。
   `| 項目 | 数値 |` の形で、素材の数字から作れるものを1つ。
   数字は**素材にある表記のまま**書き写すこと（「12件」を「12サイト」と
   言い換えない。言い換えると裏が取れない数字として弾かれます）。
4. 「## この記事で言えないこと」を置き、当社が測っていないことを列挙する。
5. 「## まとめ」を最後の節に。箇条書きで5点前後。
6. 本文は{MIN_CHARS}字以上（空白を除く）。ただし字数のために薄めない。
   書けることを書き切って足りないなら、それは素材が無いということなので
   `SKIP:` を返してください。
7. 下の「張れる内部リンク」から**2本以上**を `[記事タイトル](../slug/)` の形で張る。
   一覧に無いスラッグを書かない。
8. **外部リンクは1本も書かない。**

# 素材1: 当社の実測（自社の数字はここにあるものだけ）

{FACTS}

# 素材2: 当社サイトの運用から毎日集めている実測

{auto_facts()}

{own_metrics()}

# 張れる内部リンク

{link_lines}

# 使ってはいけない言い回し（1つでも入ると不合格になります）

いかがでしたでしょうか / いかがでしょうか / 本記事では / 詳しくは後述 /
ぜひ参考にしてください / 最後までお読みいただき / 重要なポイントです /
注目が集まっています

**ファイルには一切書き込まないこと。記事のMarkdownだけを応答として返すこと。**
前置き・後書き・コードフェンスで囲まない。書けないときは `SKIP: 理由` の1行だけ。
"""


def main() -> int:
    dry = "--dry-run" in sys.argv
    today = str(datetime.date.today())
    slugs = {p.name[: -len(".ja.md")] for p in ARTICLES.glob("*.ja.md")}
    cands = candidates()
    if not cands:
        log("商用クエリの候補がない（全部書き済みか、実測がまだ無い）")
        return 0

    material = FACTS + "\n" + auto_facts() + "\n" + own_metrics()
    for q in cands[:MAX_TRIES]:
        log(f"お題: {q['q']}（{q['imp']}表示 / 最高{q['pos']}位）")
        links = link_pool(slugs, q["q"])
        text = strip_fence(gen_with_claude(build_prompt(q, links, today)))
        if not text:
            continue
        if text.startswith("SKIP"):
            log(f"  素材不足で見送り: {text[:120]}")
            continue
        ok, why = inspect(text, slugs, material, MIN_CHARS, "", TAG)
        if not ok:
            # 落ちた理由を伝えて1回だけ書き直させる。実測では
            # 「本記事では」という言い回し1つで落ちる惜しい失敗が出た。
            # 中身は書けているのに1本捨てるのは損なので、そこだけ直させる。
            log(f"  検査に落ちた: {why} → 直させる")
            fix = (build_prompt(q, links, today)
                   + f"\n\n# 直し\n\n前回の原稿は「{why}」で不合格でした。"
                     "そこだけを直した全文を、同じ形式でもう一度出してください。"
                     "内容を薄めたり、数字を足したりしないこと。")
            text = strip_fence(gen_with_claude(fix))
            ok, why = inspect(text, slugs, material, MIN_CHARS, "", TAG) \
                if text and not text.startswith("SKIP") else (False, "再生成も不可")
        if not ok:
            log(f"  書き直しても落ちた: {why}")
            REJECTED.mkdir(parents=True, exist_ok=True)
            (REJECTED / f"commercial-{today}-{q['q'][:20]}.md").write_text(
                text or "(空)", encoding="utf-8")
            continue

        slug = re.search(r"^slug: (.+)$", text, re.M).group(1).strip()
        if dry:
            log(f"  [dry-run] 通った: {slug} / {why}")
            return 0
        (ARTICLES / f"{slug}.ja.md").write_text(text, encoding="utf-8")
        rec = written()
        rec[q["q"]] = {"slug": slug, "date": today,
                       "imp_at_write": q["imp"], "pos_at_write": q["pos"]}
        WRITTEN.write_text(json.dumps(rec, ensure_ascii=False, indent=2),
                           encoding="utf-8")
        log(f"  公開: {slug}（お題「{q['q']}」／{why}）")
        # ヒーロー画像。publish_daily.py と同じ扱いにする（無いとイメージ写真の
        # 使い回しになり、量産サイトに見える）。
        try:
            r = subprocess.run(
                [sys.executable, str(ROOT / "tools" / "gen_flux_images.py"),
                 "--articles"], capture_output=True, text=True, timeout=600)
            tail = [x for x in r.stdout.splitlines() if "===" in x]
            log("  画像: " + (tail[-1] if tail else "出力なし"))
        except Exception as e:  # noqa: BLE001
            log(f"  ⚠️ カバー画像の生成に失敗: {e}")
        return 0

    log(f"  {min(len(cands), MAX_TRIES)}件試したが通らなかった。今日は出さない")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""AEO対策室の記事を、毎日1本だけ公開する。

daily.sh から無人で呼ばれる。動きは2段構え。

  1. content/queue/ に人が書いた記事があれば、その最も古い1本を公開する（優先）
  2. 無ければ content/_aeo_themes.json の未執筆テーマを1件取り、
     claude CLI で下書きを作る → 検査に通れば公開、落ちれば公開しない

**検査に落ちたものは公開しない。** 記事が出ない日があるのは構わないが、
中身の裏が取れないものを載せると、このサイトの前提（実測しか書かない）が壊れる。
落ちた理由はログに残す（黙って0本になると気づけないため）。

捏造の防止:
  - 使ってよい数字は FACTS に列挙したものだけ。プロンプトにもそのまま渡す。
  - 生成後、本文中の「数字＋単位」を機械的に抜き出し、FACTS に無いものが
    残っていれば公開しない。一般的な件数（3つ・4点）は許可リストで除く。

実行:
    python3 tools/publish_daily.py            # 1本公開（無人運用）
    python3 tools/publish_daily.py --dry-run  # 生成と検査だけ。公開しない
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "content" / "articles"
QUEUE = ROOT / "content" / "queue"
THEMES = ROOT / "content" / "_aeo_themes.json"
DRAFT_FAIL = ROOT / "content" / "_aeo_rejected"

TAG = "AEO対策室"
AUTHOR = "AIの鬼 編集部"
MIN_CHARS = 3000          # 自動生成の下限。人が書いた記事はこれより厚い
MIN_TABLES = 1
MIN_LINKS = 2

# --- 記事に書いてよい実測値 ---------------------------------------------
# ここに無い数字を本文に出させない。すべて当サイトの既存記事に載っている実測か、
# 出典を明記して引用している外部調査の数字。
FACTS = """
【当社の実測（これ以外の自社数値を書かない）】
- 2026年7月18日、Playwright経由でPerplexityに3クエリ（業種＋条件＋地域）を投げた。
  引用元ドメインは12件で、企業の自社サイト8件、ポータル・マッチングサイト4件。
  引用ドメインは3クエリ間で1件も重複しなかった。
- 引用されていたのは「0.03mm〜1.0mmの極薄板溶接に対応」「1点から製作」
  「マシニング加工、NC旋盤加工、5軸加工に対応」のような具体的な記述の箇所。
  「高品質」「短納期」といった抽象的なキャッチコピーの箇所は引用されていなかった。
- 2026年7月22日、主要25サイトのrobots.txtを取得（成功23）。AIクローラを1つ以上
  拒否していたのは6サイト。うち3つが新聞社（朝日・読売・NYT）で6種すべて拒否。
  17サイトは明示的な拒否なし。
- 2026年7月22日、主要25サイトのllms.txtを調査。あったのは5サイト（20%）で
  ITmedia・SoftBank・GitHub・Stripe・Cloudflare。日本の大手メディア4社は無し。
  OpenAI・Anthropicにも無し。
- 2026年8月1日、福岡県の金属加工業45社を実測（Gemini Flash-Lite＋Google検索
  グラウンディング、1社3回）。公式サイトを根拠に説明できたのは42社（93%）。
  同名他社と区別されていなかったのは3社（7%）。
  項目別：事業内容100%、主力製品98%、所在地98%、従業員数・売上規模96%、
  設立年93%、取引先・納入実績76%、報道・業界メディアでの言及31%（14社）。
- 2026年8月1日、自社サイトをAI可視性チェッカーで測定。AIの鬼は10/100で
  「AIに認識されていません」、株式会社TOEは20/100。AIが根拠にした6サイトに
  自社サイトは1つも入っていなかった。原因の一つは、FAQページに別メディア
  （宇宙開発）の12問がそのまま残っていたこと。
- Search Console（2026年7月20〜29日）: 指名検索「aiの鬼」は表示24回・平均5.5位・
  クリック6件で、サイト全体のクリック25件中6件（24%）。
  ニュース個別142ページが表示の51.8%でCTR2.03%、自社記事73ページが21.1%で
  CTR4.35%、コーナー一覧ページは表示7.2%でクリックの32%・CTR14.55%。
- 自社の他媒体（gtoe.info / hojokin-oni.com / uchuchu.tech）から ai-oni.com への
  リンクは0本。
- 別メディアで sitemap から無作為抽出してURL検査した結果、インデックス済み51%、
  Googleに未認識（URL is unknown to Google）48%。

【引用してよい外部調査（出典名を必ず添える）】
- プリンストン大学ほか「GEO: Generative Engine Optimization」（KDD 2024）:
  10,000クエリ・9手法。出典の明示・統計や数値の追加・記述の具体化で可視性が30〜40%向上。
- Ahrefs: JSON-LDを追加した1,885ページ vs 対照群4,000ページ。AI Overviews −4.6%（有意）、
  AI Mode +2.4%、ChatGPT +2.2%（誤差範囲）。「有意な引用増をもたらさない」。
- Ahrefs: 75,000ブランドの相関分析。外部でのブランド言及0.664、ブランド検索
  ボリューム0.392、ドメイン評価0.326、被リンク0.218。相関であって因果ではない。
- SE Ranking: 129,000ドメイン・216,524ページ。FAQスキーマあり3.6件 vs なし4.2件。
- SearchVIU: 5つのAIが隠しSchemaを抽出できたのは0/5。
- SparkToro / Gumshoe.ai: 600人・2,961回実行。同じ質問での再現率は100回に1回未満。
- Piftee（2026年5〜6月・n=196、うち製造業37名）: 発注先探しで生成AIを使った経験75.0%、
  AI経由で知らない企業を見つけた82.3%、実際にAI経由で発注に至ったのは21.1%。
- Gartner（2026年5月・n=645）: BtoB購買担当者の51%がAIで誤情報に遭遇、
  69%が営業担当に裏取りを依頼。
- Google（2026年5月）: llms.txt・チャンキング・特殊な構造化データは生成AI検索向けに不要。
- 辻正浩氏（Web担当者Forum・2026年4月13日）: AI検索対策は多くのサイトに現段階では不要。
  「SEOでやるべきことをしっかりやること」。現状を2006〜2009年のSEO業界に酷似と批判。
"""

# 数字の照合から除く語。文章の骨格に使う一般的な数え上げまで弾くと、
# まともな記事が1本も通らなくなる。
GENERIC_NUM = re.compile(
    r"^(1|2|3|4|5|6|7|8|9|10|11|12|13|20|30|60|90|100)"
    r"(つ|点|個|項目|か所|箇所|段階|通り|種類|本|回|日|分|時間|営業日|年|月|人|名)$")


def log(msg: str) -> None:
    print(f"   {msg}", flush=True)


def slug_exists(slug: str) -> bool:
    return (ARTICLES / f"{slug}.ja.md").exists()


def existing_slugs() -> set[str]:
    return {p.name[: -len(".ja.md")] for p in ARTICLES.glob("*.ja.md")}


# --- 1. キューからの公開 -------------------------------------------------
def publish_from_queue(today: str, dry: bool) -> bool:
    """content/queue/ の最も古い1本を公開する。あれば True。"""
    if not QUEUE.exists():
        return False
    files = sorted(QUEUE.glob("*.ja.md"))
    if not files:
        return False
    src = files[0]
    text = src.read_text(encoding="utf-8")
    # 公開日を今日にそろえる（キューに入れた日ではなく出した日が公開日）
    text = re.sub(r"^date: .*$", f"date: {today}", text, count=1, flags=re.M)
    ok, why = inspect(text, existing_slugs(), strict_numbers=False)
    if not ok:
        log(f"⚠️ キューの {src.name} が検査に落ちた: {why}")
        return False
    if dry:
        log(f"[dry-run] キューから公開する予定: {src.name}")
        return True
    (ARTICLES / src.name).write_text(text, encoding="utf-8")
    src.unlink()
    log(f"✅ キューから公開: {src.name}（残り {len(files) - 1} 本）")
    if len(files) - 1 <= 2:
        log(f"⚠️ キューの残りが {len(files) - 1} 本。補充が要る")
    return True


# --- 2. テーマ在庫からの生成 --------------------------------------------
def next_theme() -> dict | None:
    data = json.loads(THEMES.read_text(encoding="utf-8"))
    for t in data["themes"]:
        if t.get("done"):
            continue
        if slug_exists(t["slug"]):     # 手で書いた場合の取りこぼしを拾う
            t["done"] = True
            continue
        return t
    return None


def mark_done(slug: str) -> None:
    data = json.loads(THEMES.read_text(encoding="utf-8"))
    for t in data["themes"]:
        if t["slug"] == slug:
            t["done"] = True
    THEMES.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")


def remaining_themes() -> int:
    data = json.loads(THEMES.read_text(encoding="utf-8"))
    return sum(1 for t in data["themes"]
               if not t.get("done") and not slug_exists(t["slug"]))


def build_prompt(theme: dict, links: list[tuple[str, str]], today: str) -> str:
    link_lines = "\n".join(f"- ../{s}/ … {t}" for s, t in links)
    return f"""あなたは「AIの鬼」（ai-oni.com、株式会社TOEが運営する中小企業向けのAI実践・実測メディア）の
編集部として、コーナー「AEO対策室」の記事を1本書きます。読者は中小企業の経営者・情報システム担当です。

# 絶対に守ること
- **下に列挙した実測値・外部調査以外の数字を、一切書かないこと。** 「約3割」「2倍」などの
  概算も禁止。数字を出すときは、下の一覧にある通りの値と条件で書く。
- 効果の保証を書かない（「対策すれば引用されます」は禁止）。当社が測っていないことは
  「測っていません」と書く。
- 株式会社TOEはAI検索対策を売りうる利害関係者である、と冒頭で明示する。
- 実在しない事例・顧客・受賞・製品名を作らない。会社名の例示は「〇〇工業株式会社」のように伏せる。

# 記事の型（必須。すべて満たすこと）
1. 1行目から `---` で囲んだフロントマターを書く。項目は
   title / excerpt / tag / author / date / hero / image_prompt / order。
   - title: 問いの形（「〜のか」「何を〜か」）。テーマの題を活かす
   - excerpt: 120〜200字。結論と、この記事で分かることを書く
   - tag: {TAG}
   - author: {AUTHOR}
   - date: {today}
   - hero: article-{theme['slug']}.jpg
   - image_prompt: 英語1行。日本人が写る明るい実写写真の指示。
     late morning / bright daylight / カメラとレンズ / 質感や生活痕を含め、
     末尾は "unretouched documentary photograph, realistic, plain unmarked surfaces,
     no text, no logos, no signage" で終える。文字・書類・図表が主役の構図にしない
   - order: 30
2. 本文は日本語のMarkdown。見出しは `##` を6本以上。
3. 「## 先に立場を明かします」から始める。
4. 次に「## 結論（先に表で）」を置き、**Markdownの表**で要点をまとめる。
5. 本文中に表を合計2つ以上、箇条書きを3つ以上入れる。
6. 「## この記事で言えないこと（限界）」を置き、測っていないことを列挙する。
7. 「## まとめ」を最後の節として置き、箇条書きで6点前後。
8. 本文の分量は3,500字以上（空白を除く）。
9. 下の「張れる内部リンク」から**2本以上**を、`[記事タイトル](../slug/)` の形で本文に張る。
   一覧に無いURLやスラッグを書かない。外部サイトへのリンクは張らない。
10. 文末に `*本記事で引用した…*` の形で、使った実測・外部調査の出典を1段落で書く。

# 今回のテーマ
題: {theme['title']}
書くこと: {theme['angle']}

# 使ってよい数字（これ以外は書かない）
{FACTS}

# 張れる内部リンク
{link_lines}

**ファイルには一切書き込まないこと。記事の本文をそのまま応答として返すこと。**
出力は記事のMarkdownだけ。前置き・後書き・コードフェンスで囲まない。
"""


def gen_with_claude(prompt: str) -> str:
    """claude CLI に本文だけを吐かせる。

    ⚠️ `--tools ""` を必ず付ける。付けないと CLI は「記事を書く」指示を
    タスクとして解釈し、**自分で content/articles/ にファイルを書いて**
    標準出力には作業報告だけを返す（2026-08-13 に実際に発生）。
    その場合、検査を通していない記事がそのまま本番に出る。
    道具を全部落として、本文をテキストで返させるのが正しい使い方。

    プロンプトは stdin から渡す。`--tools ""` の空文字を挟むと、引数として
    渡したプロンプトが --tools の値として食われて "Input must be provided" で
    落ちる（同日に踏んだ）。
    """
    model = os.environ.get("AIONI_ARTICLE_MODEL", "sonnet")
    try:
        r = subprocess.run(
            ["claude", "-p", "--model", model, "--tools", ""],
            input=prompt, capture_output=True, text=True, timeout=900)
    except FileNotFoundError:
        log("⚠️ claude CLI が見つからない")
        return ""
    except subprocess.TimeoutExpired:
        log("⚠️ 生成がタイムアウトした")
        return ""
    if r.returncode != 0:
        log(f"⚠️ 生成に失敗（rc={r.returncode}）: {r.stderr.strip()[:200]}")
        return ""
    return r.stdout.strip()


# --- 検査 ---------------------------------------------------------------
def strip_fence(text: str) -> str:
    """モデルがコードフェンスで包んで返した場合に剥がす。"""
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n", "", t)
        t = re.sub(r"\n```\s*$", "", t)
    return t.strip()


def unverified_numbers(body: str) -> list[str]:
    """FACTS に無い「数字＋単位」を拾う。捏造の最終防波堤。"""
    # 「2. 分類する」のような番号付きリストを数字扱いしないよう、
    # 小数点の後ろは数字必須・単位の直前に空白を挟まない形だけを拾う。
    found = re.findall(r"[0-9][0-9,]*(?:\.[0-9]+)?(?:%|％|社|件|ページ|ドメイン|人|倍|円|"
                       r"万円|ポイント|クエリ|サイト|本|回|時間|分|営業日)", body)
    facts = FACTS.replace(",", "")
    bad = []
    for f in found:
        norm = f.replace(" ", "").replace(",", "").replace("％", "%")
        if GENERIC_NUM.match(norm):
            continue
        if norm in facts.replace("％", "%") or norm in facts:
            continue
        # 「45社」と「45 社」など表記ゆれの吸収
        num = re.match(r"[0-9\.]+", norm).group(0)
        unit = norm[len(num):]
        if f"{num}{unit}" in facts or f"{num} {unit}" in facts:
            continue
        bad.append(f)
    return sorted(set(bad))


def inspect(text: str, slugs: set[str], strict_numbers: bool) -> tuple[bool, str]:
    if not text.startswith("---"):
        return False, "フロントマターが無い"
    parts = text.split("---", 2)
    if len(parts) < 3:
        return False, "フロントマターが閉じていない"
    fm, body = parts[1], parts[2]
    for key in ("title", "excerpt", "tag", "author", "date", "hero", "image_prompt"):
        if not re.search(rf"^{key}: \S", fm, re.M):
            return False, f"{key} が無い"
    if f"tag: {TAG}" not in fm:
        return False, "tag が AEO対策室 でない"
    chars = len(re.sub(r"\s", "", body))
    if chars < MIN_CHARS:
        return False, f"本文が短い（{chars}字）"
    if body.count("\n|---") < MIN_TABLES:
        return False, "表が無い"
    if "## まとめ" not in body:
        return False, "まとめが無い"
    if "限界" not in body:
        return False, "限界の節が無い"
    links = re.findall(r"\]\(\.\./([a-z0-9\-]+)/\)", body)
    if len(links) < MIN_LINKS:
        return False, f"内部リンクが{len(links)}本"
    dead = [x for x in links if x not in slugs]
    if dead:
        return False, f"存在しない記事へのリンク {dead}"
    if re.search(r"\]\(https?://", body):
        return False, "外部リンクが入っている"
    if strict_numbers:
        bad = unverified_numbers(body)
        if bad:
            return False, f"裏の取れない数字 {bad[:6]}"
    return True, f"{chars}字"


# --- 実行 ---------------------------------------------------------------
def main() -> int:
    dry = "--dry-run" in sys.argv
    today = datetime.date.today().isoformat()
    ARTICLES.mkdir(parents=True, exist_ok=True)

    # 同じ日に2本出さない（daily.sh が再実行されても増やさない）
    todays = [p for p in ARTICLES.glob("aeo-*.ja.md")
              if f"date: {today}" in p.read_text(encoding="utf-8")]
    if todays and not dry:
        log(f"本日分は公開済み（{len(todays)}本）。何もしない")
        return 0

    if publish_from_queue(today, dry):
        return 0

    theme = next_theme()
    if not theme:
        log("⚠️ テーマ在庫が空。content/_aeo_themes.json に追加が要る")
        return 1

    slugs = existing_slugs()
    links = []
    for s in theme.get("links", []):
        if s in slugs:
            t = re.search(r"^title: (.+)$",
                          (ARTICLES / f"{s}.ja.md").read_text(encoding="utf-8"), re.M)
            links.append((s, t.group(1).strip() if t else s))
    # 張り先が足りないときは、同じコーナーの記事から補う
    if len(links) < 4:
        for p in sorted(ARTICLES.glob("aeo-*.ja.md")):
            s = p.name[: -len(".ja.md")]
            if s in [x[0] for x in links]:
                continue
            t = re.search(r"^title: (.+)$", p.read_text(encoding="utf-8"), re.M)
            links.append((s, t.group(1).strip() if t else s))
            if len(links) >= 8:
                break

    log(f"テーマ: {theme['slug']}（在庫 残り{remaining_themes()}件）")
    text = strip_fence(gen_with_claude(build_prompt(theme, links, today)))
    if not text:
        return 1

    ok, why = inspect(text, slugs, strict_numbers=True)
    if not ok:
        DRAFT_FAIL.mkdir(parents=True, exist_ok=True)
        p = DRAFT_FAIL / f"{today}_{theme['slug']}.md"
        p.write_text(text, encoding="utf-8")
        log(f"⚠️ 検査に落ちたので公開しない: {why} → {p.relative_to(ROOT)}")
        return 1

    if dry:
        # 中身を目で見られるように残す。公開はしない
        prev = ROOT / "content" / "_aeo_preview"
        prev.mkdir(parents=True, exist_ok=True)
        p = prev / f"{today}_{theme['slug']}.md"
        p.write_text(text, encoding="utf-8")
        log(f"[dry-run] 公開可: {theme['slug']}（{why}）→ {p.relative_to(ROOT)}")
        return 0

    (ARTICLES / f"{theme['slug']}.ja.md").write_text(text, encoding="utf-8")
    mark_done(theme["slug"])
    log(f"✅ 公開: {theme['slug']}.ja.md（{why}）")

    left = remaining_themes()
    if left <= 5:
        log(f"⚠️ テーマ在庫が残り{left}件。content/_aeo_themes.json に補充が要る")

    # カバー画像。Flux鍵が無い環境では黙って飛ばさず、ログに残す
    try:
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "gen_flux_images.py"),
                            "--articles"], capture_output=True, text=True, timeout=600)
        tail = [x for x in r.stdout.splitlines() if "===" in x or "生成中" in x]
        log("画像: " + (" / ".join(tail[-2:]) if tail else "出力なし"))
    except Exception as e:
        log(f"⚠️ カバー画像の生成に失敗: {e}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

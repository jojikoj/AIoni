"""その日の旬ネタから記事を1本作って公開する。

daily.sh から無人で呼ばれる。ネタは**ストックしない**。
その日の収集データ（data/news.json）から、いま起きていることを1件選び、
その素材だけで書く（2026-08-13 方針変更・小嶋さん指示）。

  収集済みニュース → trend_news.pick() で候補 → 1件選ぶ → claude で執筆
  → 検査 → 通れば公開／落ちれば公開しない

なぜストックを持たないか:
  テーマ在庫から書くと「いつ書いても同じ記事」になる。それは既にAIが
  答えられる一般論で、引用もクリックもされない。旬（今日の出来事）と
  一次情報（原文）が乗っているものだけが、このサイトで書く価値がある。

コーナーの割り振り:
  AI検索・AEOの話 → AEO対策室 / それ以外 → AI解体新書。
  実践室・失敗の鬼・中の鬼は**自動生成しない**（自社の実測が要るため。人が書く）。

字数:
  下限は素材の量に連動させる。素材が薄い日に長い記事を書かせると、
  差は一般論と言い換えで埋まる。**薄い長文より短い記事**（小嶋さん指示）。

捏造の防止:
  書いてよい数字は「当社の実測（FACTS）」と「選んだ記事の原文に出てくる数字」だけ。
  生成後に本文の数字を機械照合し、どちらにも無い数字が残っていれば公開しない。

実行:
    python3 tools/publish_daily.py             # 1本公開（無人運用）
    python3 tools/publish_daily.py --dry-run   # 生成と検査だけ。公開しない
    python3 tools/publish_daily.py --days 7    # 候補を探す期間（既定3日→無ければ7日）
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from trend_news import pick as pick_trends      # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "content" / "articles"
NEWS = ROOT / "data" / "news.json"
REJECTED = ROOT / "content" / "_aeo_rejected"
PREVIEW = ROOT / "content" / "_aeo_preview"

AUTHOR = "AIの鬼 編集部"

# AI検索・AEOの話かどうか。当たれば AEO対策室、外れれば AI解体新書。
#
# 強い語は1つでAEOと判定する。弱い語（google・chatgpt 等）は一般のAIニュースにも
# 普通に出るので、2つ以上そろって初めてAEOとみなす。ここを緩めると、
# LLMの資金調達の話が「AI検索対策」の棚に並ぶ（2026-08-13 に実際に誤判定した）。
AEO_STRONG = ("ai検索", "aeo", "ai overview", "aioverview", "perplexity",
              "llms.txt", "robots.txt", "クローラ", "crawler", "被引用",
              "生成エンジン最適化", "ゼロクリック", "zero-click", "検索結果",
              "検索順位", "seo", "インデックス", "sge", "検索エンジン")
AEO_WEAK = ("google", "chatgpt", "gemini", "検索", "search", "引用", "出典",
            "可視性", "オーガニック", "流入")

# 水増し表現。1つでも出たら公開しない（字数を埋めるための文の典型）。
PADDING = ("いかがでしたでしょうか", "いかがでしょうか", "詳しくは後述",
           "本記事では", "ぜひ参考にしてください", "最後までお読みいただき",
           "重要なポイントです", "注目が集まっています")

MIN_TABLES = 1
MIN_LINKS = 2

# --- 当社の実測（この一覧に無い自社数値を書かせない）---------------------
FACTS = """
【当社（株式会社TOE / AIの鬼）の実測。自社の数字はここにあるものだけ】
- 2026年7月18日、Playwright経由でPerplexityに3クエリ（業種＋条件＋地域）を投げた。
  引用元ドメイン12件のうち、企業の自社サイト8件、ポータル・マッチングサイト4件。
  引用ドメインは3クエリ間で1件も重複しなかった。
- 引用されていたのは「0.03mm〜1.0mmの極薄板溶接に対応」「1点から製作」のような
  具体的な記述の箇所。「高品質」「短納期」等の抽象的なキャッチコピーの箇所ではない。
- 2026年7月22日、主要25サイトのrobots.txtを取得（成功23）。AIクローラを1つ以上
  拒否していたのは6サイト。うち3つが新聞社で6種すべて拒否。17サイトは明示的な拒否なし。
- 2026年7月22日、主要25サイトのllms.txtを調査。あったのは5サイト（20%）。
  日本の大手メディア4社は無し。OpenAI・Anthropicにも無し。
- 2026年8月1日、福岡県の金属加工業45社を実測（Gemini Flash-Lite＋Google検索
  グラウンディング、1社3回）。公式サイトを根拠に説明できたのは42社（93%）、
  同名他社と区別されていなかったのは3社（7%）。項目別は 事業内容100%／主力製品98%／
  所在地98%／従業員数・売上規模96%／設立年93%／取引先・納入実績76%／
  報道・業界メディアでの言及31%（14社）。
- 2026年8月1日、自社サイトをAI可視性チェッカーで測定。AIの鬼10/100、株式会社TOE20/100。
  AIが根拠にした6サイトに自社サイトは1つも入っていなかった。
- Search Console（2026年7月20〜29日）: 指名検索「aiの鬼」は表示24回・平均5.5位・
  クリック6件（サイト全体のクリック25件中6件）。ニュース個別142ページが表示の51.8%で
  CTR2.03%、自社記事73ページが21.1%でCTR4.35%、コーナー一覧ページは表示7.2%で
  クリックの32%・CTR14.55%。
- 自社の他媒体（gtoe.info / hojokin-oni.com / uchuchu.tech）から ai-oni.com への
  リンクは0本。
- 社内業務の自動化は27本。AI秘書のブリーフィングは毎朝8:00。運用中のAI API課金は0円。

【引用してよい外部調査（出典名を必ず添える）】
- プリンストン大学ほか「GEO: Generative Engine Optimization」（KDD 2024）:
  10,000クエリ・9手法。記述の具体化・数値と出典の追加で可視性が30〜40%向上。
- Ahrefs: JSON-LD追加1,885ページ vs 対照群4,000ページ。AI Overviews −4.6%（有意）。
- Ahrefs: 75,000ブランドの相関分析。外部言及0.664／ブランド検索0.392／
  ドメイン評価0.326／被リンク0.218。相関であって因果ではない。
- SE Ranking: 129,000ドメイン・216,524ページ。FAQあり3.6件 vs なし4.2件。
- SearchVIU: 5つのAIが隠しSchemaを抽出できたのは0/5。
- SparkToro / Gumshoe.ai: 600人・2,961回実行。同一質問での再現率は100回に1回未満。
- Piftee（2026年5〜6月・n=196）: 発注先探しで生成AI利用75.0%、AI経由で企業発見82.3%、
  AI経由で発注に至ったのは21.1%。
- Gartner（2026年5月・n=645）: BtoB購買担当者の51%がAIで誤情報に遭遇、69%が裏取りを依頼。
- Google（2026年5月）: llms.txt・特殊な構造化データは生成AI検索向けに不要。
- 辻正浩氏（Web担当者Forum・2026年4月13日）: AI検索対策は多くのサイトに現段階では不要。
"""

GENERIC_NUM = re.compile(
    r"^(1|2|3|4|5|6|7|8|9|10|11|12|13|20|30|60|90|100)"
    r"(つ|点|個|項目|か所|箇所|段階|通り|種類|本|回|日|分|時間|営業日|年|月|人|名)$")


def log(msg: str) -> None:
    print(f"   {msg}", flush=True)


def existing_slugs() -> set[str]:
    return {p.name[: -len(".ja.md")] for p in ARTICLES.glob("*.ja.md")}


# --- 素材 ---------------------------------------------------------------
def load_source(url: str) -> dict:
    """選んだニュースの原文・自社解説を data/news.json から拾う。"""
    data = json.loads(NEWS.read_text(encoding="utf-8"))
    for it in data.get("items", []):
        if it.get("url") == url:
            return it
    return {}


def material_text(item: dict) -> str:
    parts = [
        item.get("title_ja") or item.get("title") or "",
        item.get("summary_ja") or item.get("summary") or "",
        (item.get("body_long") or ""),
        (item.get("body_src") or "")[:12000],   # 原文は長すぎると入り切らない
    ]
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def min_chars_for(material: str) -> int:
    """字数の下限を素材の量に連動させる。薄い長文を作らせないため。

    下限は「素材から書ける量」。ここを高く置くと、差は一般論と言い換えで
    埋まる（＝AEOでいちばん弱い記事になる）。実測でも 2,753字の素材に
    1,800字を求めると僅差で落ちたので、素材に対して欲張らない値にしてある。
    """
    n = len(re.sub(r"\s", "", material))
    if n >= 8000:
        return 3000
    if n >= 3000:
        return 2200
    return 1500


def corner_for(item: dict) -> tuple[str, str]:
    blob = ((item.get("title") or "") + (item.get("title_ja") or "")
            + (item.get("summary_ja") or "")[:300]).lower()
    if any(k in blob for k in AEO_STRONG):
        return "AEO対策室", "aeo"
    if sum(1 for k in AEO_WEAK if k in blob) >= 2:
        return "AEO対策室", "aeo"
    return "AI解体新書", "kaisetsu"


# --- 生成 ---------------------------------------------------------------
def build_prompt(item: dict, tag: str, links: list[tuple[str, str]],
                 today: str, min_chars: int, url: str, source: str) -> str:
    link_lines = "\n".join(f"- ../{s}/ … {t}" for s, t in links)
    corner_note = {
        "AEO対策室": "このコーナーは「AI検索（ChatGPT・Perplexity・AI Overviews）に"
                     "自社を見つけさせ、正しく説明させるための実務」を扱う。"
                     "読者が明日自社で何をすればよいかに必ず着地させる。",
        "AI解体新書": "このコーナーは「外部の研究・調査・事例を中小企業向けに読み解く」。"
                      "解説で終わらせず、中小企業にとって何が変わるのかを書く。",
    }[tag]
    return f"""あなたは「AIの鬼」（ai-oni.com、株式会社TOEが運営する中小企業向けのAI実践・実測メディア）の
編集部として、**今日のニュースを題材にした記事**を1本書きます。読者は中小企業の経営者・情報システム担当です。

# 題材（この1件だけを扱う）
見出し: {item.get('title_ja') or item.get('title')}
配信元: {source}
公開日: {(item.get('published') or '')[:10]}
出典URL: {url}

## 素材（この中に書いてあることだけを事実として扱う）
{material_text(item)}

# 絶対に守ること
- **素材と、下の「当社の実測」に書かれていない事実・数字を、一切書かないこと。**
  「約3割」「2倍」などの概算も禁止。推測を事実として書かない。
  素材から読み取れないことは「素材からは分からない」と書く。
- 効果や成果の保証を書かない。当社が測っていないことは「測っていません」と書く。
- 株式会社TOEはAI検索対策・AI導入支援を売りうる利害関係者である、と明示する。
- 実在しない事例・顧客・受賞・製品名を作らない。会社名の例示は「〇〇工業株式会社」と伏せる。
- **字数を満たすために内容を薄めない。** その段落を消して読者が失う情報が無いなら、消す。
  「いかがでしたでしょうか」「本記事では」「詳しくは後述します」等の埋め草は禁止。
- **文体は敬体（です・ます）。** 常体（〜だ・〜である）で書かない。既存記事と揃える。

# コーナー
{tag} … {corner_note}

# 記事の型（すべて満たすこと）
1. 1行目から `---` で囲んだフロントマターを書く。項目は
   slug / title / excerpt / tag / author / date / hero / image_prompt / order。
   - slug: 内容が分かる英小文字とハイフンのみ（6〜60字）。日付や連番を入れない
   - title: 問いの形。何が起きて、読者にとって何が変わるのかが分かる見出しにする
   - excerpt: 120〜200字。結論を先に書く
   - tag: {tag}
   - author: {AUTHOR}
   - date: {today}
   - hero: article-<上で決めたslug>.jpg
   - image_prompt: 英語1行。日本人が写る明るい実写写真の指示。late morning /
     bright daylight / カメラとレンズ / 生活痕を入れ、末尾は
     "unretouched documentary photograph, realistic, plain unmarked surfaces,
     no text, no logos, no signage" で終える。文字・書類・図表が主役の構図にしない
   - order: 30
2. 本文は日本語のMarkdown。`##` の見出しを4本以上。
3. 冒頭200字以内で結論を言い切る。
4. **Markdownの表を1つ以上**入れる（比較・時系列・影響範囲など、素材から作れるもの）。
5. 「## この記事で言えないこと」を置き、素材から分からないこと・当社が測っていないことを列挙する。
6. 「## まとめ」を最後の節として置き、箇条書きで5点前後。
7. 本文は**{min_chars}字以上**（空白を除く。目安は{int(min_chars * 1.2)}字）。
   ただし字数のために内容を薄めない。素材から書けることを全部書いた結果が
   下限すれすれなら、それでよい。水増しは検査で弾かれる。
8. 下の「張れる内部リンク」から**2本以上**を `[記事タイトル](../slug/)` の形で本文に張る。
   一覧に無いスラッグを書かない。
9. 外部リンクは**出典URL1本だけ**許可する（`[配信元名](出典URL)` の形で1回だけ）。他のURLは書かない。
10. 文末に `*この記事は…を素材に、…の実測とあわせて書きました。*` の形で、
    素材の配信元と、引用した当社実測・外部調査の名前を1段落で書く。

# 当社の実測（自社の数字はここにあるものだけ）
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

    プロンプトは stdin から渡す。`--tools ""` の空文字を挟むと、引数として
    渡したプロンプトが --tools の値として食われて落ちる。
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
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n", "", t)
        t = re.sub(r"\n```\s*$", "", t)
    return t.strip()


def unverified_numbers(body: str, material: str) -> list[str]:
    """当社実測にも素材にも無い「数字＋単位」を拾う。捏造の最終防波堤。"""
    found = re.findall(r"[0-9][0-9,]*(?:\.[0-9]+)?(?:%|％|社|件|ページ|ドメイン|人|倍|円|"
                       r"万円|億円|ドル|ポイント|クエリ|サイト|本|回|時間|分|営業日)", body)
    hay = (FACTS + "\n" + material).replace(",", "").replace("％", "%")
    bad = []
    for f in found:
        norm = f.replace(" ", "").replace(",", "").replace("％", "%")
        if GENERIC_NUM.match(norm):
            continue
        if norm in hay:
            continue
        num = re.match(r"[0-9\.]+", norm).group(0)
        unit = norm[len(num):]
        if f"{num}{unit}" in hay or f"{num} {unit}" in hay:
            continue
        bad.append(f)
    return sorted(set(bad))


def inspect(text: str, slugs: set[str], material: str, min_chars: int,
            allowed_url: str, tag: str) -> tuple[bool, str]:
    if not text.startswith("---"):
        return False, "フロントマターが無い"
    parts = text.split("---", 2)
    if len(parts) < 3:
        return False, "フロントマターが閉じていない"
    fm, body = parts[1], parts[2]
    for key in ("slug", "title", "excerpt", "tag", "author", "date", "hero", "image_prompt"):
        if not re.search(rf"^{key}: \S", fm, re.M):
            return False, f"{key} が無い"
    if f"tag: {tag}" not in fm:
        return False, f"tag が {tag} でない"
    m = re.search(r"^slug: (.+)$", fm, re.M)
    slug = m.group(1).strip().strip('"').strip("'")
    if not re.fullmatch(r"[a-z0-9][a-z0-9\-]{4,59}", slug):
        return False, f"slugの形式が不正 ({slug})"
    if slug in slugs:
        return False, f"slugが既存記事と重複 ({slug})"
    if f"article-{slug}.jpg" not in fm:
        return False, "hero が slug と一致しない"
    chars = len(re.sub(r"\s", "", body))
    if chars < min_chars:
        return False, f"本文が短い（{chars}字 < {min_chars}字）"
    if body.count("\n|---") < MIN_TABLES:
        return False, "表が無い"
    if "## まとめ" not in body:
        return False, "まとめが無い"
    if "言えないこと" not in body:
        return False, "言えないことの節が無い"
    pad = [p for p in PADDING if p in body]
    if pad:
        return False, f"水増し表現 {pad}"
    links = re.findall(r"\]\(\.\./([a-z0-9\-]+)/\)", body)
    if len(links) < MIN_LINKS:
        return False, f"内部リンクが{len(links)}本"
    dead = [x for x in links if x not in slugs]
    if dead:
        return False, f"存在しない記事へのリンク {dead}"
    ext = re.findall(r"\]\((https?://[^)]+)\)", body)
    bad_ext = [u for u in ext if u.rstrip("/") != (allowed_url or "").rstrip("/")]
    if bad_ext:
        return False, f"許可外の外部リンク {bad_ext[:3]}"
    bad = unverified_numbers(body, material)
    if bad:
        return False, f"裏の取れない数字 {bad[:6]}"
    return True, f"{slug} / {chars}字"


# --- 実行 ---------------------------------------------------------------
def link_pool(tag: str, slugs: set[str]) -> list[tuple[str, str]]:
    """張り先の候補。同じコーナーの記事を優先し、足りなければAEO対策室から補う。"""
    out = []
    for p in sorted(ARTICLES.glob("*.ja.md")):
        t = p.read_text(encoding="utf-8")
        if f"tag: {tag}" not in t:
            continue
        m = re.search(r"^title: (.+)$", t, re.M)
        out.append((p.name[: -len(".ja.md")], m.group(1).strip() if m else ""))
    out = out[-10:]
    if len(out) < 4:
        for p in sorted(ARTICLES.glob("aeo-*.ja.md"))[:8]:
            s = p.name[: -len(".ja.md")]
            if s in [x[0] for x in out]:
                continue
            m = re.search(r"^title: (.+)$", p.read_text(encoding="utf-8"), re.M)
            out.append((s, m.group(1).strip() if m else s))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--days", type=int, default=3)
    a = ap.parse_args()

    today = datetime.date.today().isoformat()
    ARTICLES.mkdir(parents=True, exist_ok=True)

    # 同じ日に2本出さない（daily.sh の再実行で増やさない）
    if not a.dry_run:
        for p in ARTICLES.glob("*.ja.md"):
            head = p.read_text(encoding="utf-8")[:400]
            if f"date: {today}" in head and "order: 30" in head:
                log(f"本日分は公開済み（{p.name}）。何もしない")
                return 0

    # 旬ネタの候補。3日で見つからなければ7日まで広げる
    picks = pick_trends(days=a.days, limit=10)
    if not picks:
        picks = pick_trends(days=7, limit=10)
    if not picks:
        log("⚠️ 直近7日に書けるニュースが無い。今日は公開しない")
        return 1

    slugs = existing_slugs()
    for cand in picks[:5]:                      # 上位5件まで順に試す
        item = load_source(cand["url"])
        if not item:
            continue
        material = material_text(item)
        if len(re.sub(r"\s", "", material)) < 400:
            continue                            # 見出しだけのものは書けない
        tag, cat = corner_for(item)
        min_chars = min_chars_for(material)
        links = link_pool(tag, slugs)
        log(f"題材: [{tag}] {cand['title'][:46]}（旬度{cand['score']}・"
            f"素材{len(material)}字・下限{min_chars}字）")

        prompt = build_prompt(item, tag, links, today, min_chars,
                              cand["url"], cand["source"])
        text = strip_fence(gen_with_claude(prompt))
        if not text:
            continue

        ok, why = inspect(text, slugs, material, min_chars, cand["url"], tag)
        if not ok:
            # 1回だけ直させる。落ちる理由の多くは字数の僅差か、素材に無い数字を
            # 1〜2個混ぜたことで、どちらも指摘すれば直る。ここで諦めて次の候補に
            # 移ると、旬度の高いネタを毎回捨てることになる。
            log(f"検査に落ちた（{why}）。1回だけ直させる")
            fix = (prompt + "\n\n# 直前に書いた記事\n" + text +
                   f"\n\n# 差し戻しの理由\n{why}\n\n"
                   "この理由だけを直した完成版を、同じ形式で最初から出力してください。"
                   "**裏の取れない数字を指摘された場合は、その数字を使う文を消すか、"
                   "素材にある表現に置き換える（別の数字に言い換えない）。**"
                   "字数不足を指摘された場合は、素材の中でまだ書いていない事実を探して"
                   "足す。無いものを足さない。一般論で埋めない。")
            text = strip_fence(gen_with_claude(fix))
            ok, why = inspect(text, slugs, material, min_chars,
                              cand["url"], tag) if text else (False, "再生成が空")
        if not ok:
            REJECTED.mkdir(parents=True, exist_ok=True)
            p = REJECTED / f"{today}_{re.sub(r'[^a-zA-Z0-9]+', '-', cand['title'])[:40]}.md"
            p.write_text(text, encoding="utf-8")
            log(f"⚠️ 検査に落ちた: {why} → {p.relative_to(ROOT)}。次の候補へ")
            continue

        slug = re.search(r"^slug: (.+)$", text.split("---", 2)[1], re.M).group(1).strip()
        # slug 行は front matter に残しても害はないが、他の記事に無い項目なので落とす
        text = re.sub(r"^slug: .*\n", "", text, count=1, flags=re.M)

        if a.dry_run:
            PREVIEW.mkdir(parents=True, exist_ok=True)
            p = PREVIEW / f"{today}_{slug}.md"
            p.write_text(text, encoding="utf-8")
            log(f"[dry-run] 公開可: {why} → {p.relative_to(ROOT)}")
            return 0

        (ARTICLES / f"{slug}.ja.md").write_text(text, encoding="utf-8")
        log(f"✅ 公開: {slug}.ja.md（{why}）")

        try:
            r = subprocess.run([sys.executable, str(ROOT / "tools" / "gen_flux_images.py"),
                                "--articles"], capture_output=True, text=True, timeout=600)
            tail = [x for x in r.stdout.splitlines() if "===" in x]
            log("画像: " + (tail[-1] if tail else "出力なし"))
        except Exception as e:
            log(f"⚠️ カバー画像の生成に失敗: {e}")
        return 0

    log("⚠️ 候補5件とも検査に落ちた。今日は公開しない（下書きは _aeo_rejected/）")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

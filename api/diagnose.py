"""AI可視性チェッカー — Vercel Python Serverless Function。

会社名を受け取り、Gemini 2.5 Flash-Lite + Google検索グラウンディングで
「生成AIがその会社をどう認識しているか」をその場で実測して返す。

方針:
  - 依存は Python 標準ライブラリのみ（requirements 不要 / @vercel/python が自動処理）。
  - APIキー(GEMINI_API_KEY)はサーバー側の環境変数だけに置き、フロントには絶対に出さない。
  - 捏造しない。Gemini が検索で得た事実と、実際に参照したソースだけを返す。
    認識できなければ「認識していない」と正直に返す。

課金暴走への防御（外部サービス不要で完結させている）:
  グラウンディングは課金プロジェクトのキーで動くため、いたずら連打が実費になる。
  Cloudflare Turnstile は他社アカウントが要るので、代わりに次の3段で守る。
    1. Origin 強制 — ai-oni.com 以外からの POST を拒否。ブラウザは
       クロスオリジンPOSTで必ず Origin を送るため、curl/bot の直叩きを弾ける。
    2. IPごとのレート制限 — ウォームインスタンス内で保持する簡易スライディング窓。
    3. インスタンス単位の日次上限 — 万一すり抜けても総量で頭打ちにする。
  Vercel はステートレスなのでインスタンスをまたぐ厳密な制限にはならないが、
  「1台のbotが連打して課金が爆発する」という現実的な最悪ケースは止められる。
  Turnstile の検証も残してあり、TURNSTILE_SECRET を入れれば追加で有効になる。
"""

from http.server import BaseHTTPRequestHandler
import json
import os
import time
import urllib.request
import urllib.error
import urllib.parse

# 具体版 gemini-2.5-flash-lite は新規ユーザー提供終了で404になる。
# 最新エイリアス gemini-flash-lite-latest を使う（HANDOFF §4）。
MODEL = "gemini-flash-lite-latest"
ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    + MODEL
    + ":generateContent"
)

# Cloudflare Turnstile の検証エンドポイント。
# 環境変数 TURNSTILE_SECRET が設定されているときだけ検証を行う（保険）。
TURNSTILE_VERIFY = "https://challenges.cloudflare.com/turnstile/v0/siteverify"

MAX_BODY = 4000        # リクエストボディ上限（byte）。Turnstileトークン分を見て拡張
MAX_FIELD = 80         # 各入力欄の最大文字数

# 本番サイト(GitHub Pages)は別オリジンなので、そこからの呼び出しだけ許可する。
# ai-oni.com のフロントからこの Vercel Function を叩く前提。
ALLOWED_ORIGINS = {
    "https://ai-oni.com",
    "https://www.ai-oni.com",
}
DEFAULT_ORIGIN = "https://ai-oni.com"

# --- レート制限のパラメータ ---------------------------------------------
# 実測は1回2〜3秒。人間が真面目に使うなら数回で足りるので、
# 「普通の見込み客は絶対に引っかからないが、連打は止まる」水準に置く。
RATE_WINDOW = 3600     # 集計窓（秒）
RATE_PER_IP = 8        # 同一IPが RATE_WINDOW 内に実行できる回数
DAILY_CAP = 300        # このインスタンスが1日に通す上限（暴走の最終ブレーキ）

# ウォームなインスタンスの間だけ保持する。コールドスタートで消えるが、
# 連打は同一インスタンスに流れやすいので実用上は効く。
_hits = {}             # ip -> [timestamp, ...]
_daily = {"day": None, "count": 0}


def _client_ip(headers):
    fwd = headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return headers.get("X-Real-IP", "") or "unknown"


def _rate_limited(ip):
    """レート超過なら True。副作用として今回の実行を記録する。"""
    now = time.time()

    day = time.strftime("%Y-%m-%d", time.gmtime(now))
    if _daily["day"] != day:
        _daily["day"], _daily["count"] = day, 0
    if _daily["count"] >= DAILY_CAP:
        return True

    recent = [t for t in _hits.get(ip, []) if now - t < RATE_WINDOW]
    if len(recent) >= RATE_PER_IP:
        _hits[ip] = recent
        return True

    recent.append(now)
    _hits[ip] = recent
    _daily["count"] += 1

    # 古いIPを掃除してメモリを膨らませない
    if len(_hits) > 2000:
        for k in [k for k, v in _hits.items() if not v or now - v[-1] > RATE_WINDOW]:
            _hits.pop(k, None)
    return False


def _build_prompt(company, product):
    lines = [
        "あなたは、中小企業の経営者に代わって「生成AIが自社をどう認識しているか」を",
        "調べるアシスタントです。Google検索を使って次の会社について調べてください。",
        "",
        "会社名: " + company,
    ]
    if product:
        lines.append("主力の製品・サービス: " + product)
    lines += [
        "",
        "調べた上で、日本語で簡潔に次を答えてください（合計4〜6文程度）:",
        "1) この会社が何をしている会社か、AIとして説明できる情報が検索で見つかったか。",
        "2) 見つかった場合、その事業内容の概要。",
        "3) 公式サイトなど信頼できる情報源が見つかったか。",
        "",
        "重要な制約:",
        "- 推測で内容を補わないでください。検索で分かった事実だけを述べてください。",
        "- 情報がほとんど見つからない場合は、正直に「情報が少ない」と述べてください。",
        "- 特定の会社を宣伝したり評価を誇張したりしないでください。",
        "",
        "最後に、説明文とは別の行として、次の形式の1行だけを必ず出力してください。",
        "JUDGE: found=<yes|no>; official=<yes|no>; ambiguous=<yes|no>",
        "  found       … その会社を特定でき、事業内容を説明できたか",
        "  official    … その会社自身の公式サイトを情報源として確認できたか"
        "（求人サイト・企業データベース・百科事典は公式ではありません）",
        "  ambiguous   … 同じ社名の会社が複数あり、どの会社か特定できない場合は yes",
        "- 評価を甘くしないでください。確認できないものは no / 低い数字にしてください。",
    ]
    return "\n".join(lines)


def _verify_turnstile(token, remote_ip=""):
    """Turnstile トークンを検証。TURNSTILE_SECRET 未設定なら検証せず素通し(True)。"""
    secret = os.environ.get("TURNSTILE_SECRET")
    if not secret:
        return True
    if not token:
        return False
    data = urllib.parse.urlencode(
        {"secret": secret, "response": token, "remoteip": remote_ip}
    ).encode("utf-8")
    req = urllib.request.Request(TURNSTILE_VERIFY, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            out = json.loads(resp.read().decode("utf-8"))
        return bool(out.get("success"))
    except Exception:
        return False


def _call_gemini(company, product):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    body = {
        "contents": [{"parts": [{"text": _build_prompt(company, product)}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 700},
    }
    req = urllib.request.Request(
        ENDPOINT + "?key=" + key,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_judge(text):
    """末尾のJUDGE行を取り出し、表示用テキストからは取り除く。

    行が無い／壊れている場合は None を返し、呼び出し側で保守的に採点する。
    """
    judge = None
    kept = []
    for line in text.splitlines():
        s = line.strip()
        if s.upper().startswith("JUDGE:"):
            body = s.split(":", 1)[1]
            d = {}
            for part in body.split(";"):
                if "=" in part:
                    k, v = part.split("=", 1)
                    d[k.strip().lower()] = v.strip().lower()
            judge = {
                "found": d.get("found") == "yes",
                "official": d.get("official") == "yes",
                "ambiguous": d.get("ambiguous") == "yes",
            }
            continue
        kept.append(line)
    return "\n".join(kept).strip(), judge


def _parse(raw):
    text = ""
    sources = []
    try:
        cand = raw["candidates"][0]
        for part in cand.get("content", {}).get("parts", []):
            if "text" in part:
                text += part["text"]
        meta = cand.get("groundingMetadata", {})
        seen = set()
        for chunk in meta.get("groundingChunks", []):
            web = chunk.get("web", {})
            uri = web.get("uri")
            if uri and uri not in seen:
                seen.add(uri)
                sources.append({"title": web.get("title", ""), "uri": uri})
    except (KeyError, IndexError, TypeError):
        pass
    return text.strip(), sources


# 第三者のデータベース・求人・百科事典など。ここに載っていても
# 「その会社自身が発信できている」ことにはならないので、公式扱いしない。
AGGREGATOR_DOMAINS = (
    "wikipedia.org", "ipros.com", "salesnow.jp", "baseconnect.in", "houjin.jp",
    "houjin-bangou.nta.go.jp", "gbiz-info.go.jp", "info.gbiz.go.jp", "alarmbox.jp",
    "tsr-net.co.jp", "tdb.co.jp", "itp.ne.jp", "navit-j.com", "ekiten.jp",
    "mynavi.jp", "rikunabi.com", "en-japan.com", "doda.jp", "indeed.com",
    "openwork.jp", "en-hyouban.com", "job-medley.com", "hellowork.mhlw.go.jp",
    "wantedly.com", "green-japan.com", "facebook.com", "twitter.com", "x.com",
    "instagram.com", "note.com", "ameblo.jp", "hatenablog.com", "fc2.com",
    "livedoor.jp", "google.com", "goo.ne.jp", "yahoo.co.jp", "navitime.co.jp",
    "mapion.co.jp", "prtimes.jp",
)


def _domains(sources):
    out = []
    for s in sources:
        uri = s.get("uri") or ""
        host = ""
        try:
            host = urllib.parse.urlparse(uri).netloc.lower()
        except Exception:
            host = ""
        # groundingChunk の title には実サイトのドメインが入ることが多い
        if not host or "vertexaisearch" in host or "googleapis" in host:
            host = (s.get("title") or "").lower()
        host = host.replace("www.", "").strip()
        if host and host not in out:
            out.append(host)
    return out


# 求人・企業DBは無数にあり列挙しきれないので、ドメイン名の語でも判定する。
AGGREGATOR_WORDS = (
    "job", "kyujin", "recruit", "recruiting", "work", "career", "baito",
    "hellowork", "shukatsu", "tenshoku", "hakenn", "haken", "kuchikomi",
    "houjin", "kigyo", "corp-db", "companydb", "townpage", "tenpo",
    # 商工会議所・商工会・産業振興系の名簿も「第三者に載っているだけ」
    "cci", "shokokai", "shinko", "sangyo",
)


def _is_aggregator(domain):
    if any(domain == a or domain.endswith("." + a) for a in AGGREGATOR_DOMAINS):
        return True
    head = domain.split(".")[0]
    return any(w in head for w in AGGREGATOR_WORDS)


def _judge_level(text, sources, judge=None):
    """AI可視性を3段階で判定する。

    設計方針（2026-07-29 全面刷新）:
      旧版は0-100点だったが、点数の大半が「検索で何件返ったか」と
      モデルの主観評価(specificity 0-3)に依存していた。どちらも実行ごとに
      変わるため、同じ会社を3回測ると 86/76/92 と振れ、判定まで反転した
      （実測）。客が2回試して違う結果が出るツールは信用されない。

      そこで、実行ごとにブレない二値の事実だけで判定する:
        レベル1 … AIが会社を特定できない
        レベル2 … 説明はできるが、根拠に公式サイトが無い（第三者情報だけ）
        レベル3 … 公式サイトを根拠に説明できている
      件数やモデルの主観点は判定に使わない（表示の補足にのみ使う）。

    戻り値: (level, found, official, third_party_present)
    """
    if not text:
        return 1, False, False, False

    low = text[:80]
    poor = ("情報が少な" in low) or ("情報が乏し" in low) or ("見つかりません" in low) \
        or ("見つかりませんでした" in text[:150]) or ("特定できません" in low)

    domains = _domains(sources)
    non_agg = [d for d in domains if not _is_aggregator(d)]

    if judge is None:
        # JUDGE行が無いときは保守的に（甘くしない）
        judge = {"found": (not poor) and len(text) > 80 and len(domains) > 0,
                 "official": len(non_agg) > 0}

    found = bool(judge.get("found")) and not poor

    # 実測で分かったこと: モデルのJUDGEは毎回同じでも、groundingChunks は
    # 返ってくる回と 0 件の回がある（TOEを4回測って 4件/0件/0件/3件）。
    # ドメインの有無をそのまま判定に使うと、同じ会社がレベル3と2で反転する。
    # そこで「証拠がある時だけ証拠を優先し、無い時はモデルの判定に従う」。
    has_evidence = len(domains) > 0
    if has_evidence:
        # 根拠が第三者DB・求人・名簿しか無いなら、公式が使われたとは言えない
        official = len(non_agg) > 0
    else:
        official = bool(judge.get("official"))

    # 公式以外の独立した情報源。証拠が無い回は判断できないので False 固定にせず、
    # 文言側で「証拠あり」のときだけ使う。
    third = has_evidence and len([
        d for d in non_agg if not (official and non_agg and d == non_agg[0])
    ]) > 0

    # 同名の会社が複数あって特定できない場合。実測では「有限会社山田製作所」で
    # found が yes/no に揺れた。これは論理の穴ではなく実態なので、
    # 揺れを判定に持ち込まず「特定できない」として独立に扱う。
    if bool(judge.get("ambiguous")):
        return 0, False, False, False

    if not found:
        return 1, False, False, False
    return (3 if official else 2), True, official, third


class handler(BaseHTTPRequestHandler):
    def _cors_origin(self):
        origin = self.headers.get("Origin", "")
        return origin if origin in ALLOWED_ORIGINS else DEFAULT_ORIGIN

    def _send(self, code, obj):
        payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(payload)

    def do_OPTIONS(self):
        # CORS プリフライト（Content-Type: application/json の POST で発生）
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self._cors_origin())
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "86400")
        self.send_header("Vary", "Origin")
        self.end_headers()

    def do_POST(self):
        # ① Origin 強制。ブラウザはクロスオリジンPOSTで必ず Origin を送るので、
        #    ここを通れないのは bot / 直叩き。課金を伴う処理の手前で落とす。
        if self.headers.get("Origin", "") not in ALLOWED_ORIGINS:
            return self._send(403, {"error": "このURLからは利用できません"})

        # ② レート制限。人間の利用では踏まない水準（1時間に8回まで）。
        if _rate_limited(_client_ip(self.headers)):
            return self._send(429, {"error": "お試しが集中しています。しばらく時間をおいてからお願いします"})

        try:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0 or length > MAX_BODY:
                return self._send(413, {"error": "入力が長すぎます"})
            data = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, TypeError):
            return self._send(400, {"error": "リクエストが不正です"})

        company = (data.get("company") or "").strip()[:MAX_FIELD]
        product = (data.get("product") or "").strip()[:MAX_FIELD]
        if not company:
            return self._send(400, {"error": "会社名を入力してください"})

        # レート制限（いたずら連打によるGemini課金暴走を防ぐ保険）。
        # TURNSTILE_SECRET が未設定なら検証はスキップされ、従来通り素通しで動く。
        token = (data.get("turnstile_token") or "").strip()
        remote_ip = (self.headers.get("X-Forwarded-For", "").split(",")[0]).strip()
        if not _verify_turnstile(token, remote_ip):
            return self._send(403, {"error": "認証に失敗しました。ページを再読み込みしてお試しください"})

        try:
            raw = _call_gemini(company, product)
        except urllib.error.HTTPError:
            return self._send(502, {"error": "AI実測サービスが混み合っています。時間をおいてお試しください"})
        except urllib.error.URLError:
            return self._send(502, {"error": "AI実測サービスに接続できませんでした"})
        except RuntimeError:
            return self._send(500, {"error": "サーバー設定エラー（APIキー未設定）"})
        except Exception:
            return self._send(500, {"error": "実測に失敗しました"})

        text, sources = _parse(raw)
        text, judge = _extract_judge(text)
        level, recognized, official, third = _judge_level(text, sources, judge)
        self._send(200, {
            "company": company,
            "recognized": recognized,
            # 0-100の点数は廃止した。実行ごとに振れて判定まで反転したため
            # （同一企業3回で 86/76/92）。ブレない3段階だけを返す。
            "level": level,
            "official": official,
            "third_party": third,
            "summary": text,
            "sources": sources[:6],
        })

    def do_GET(self):
        self._send(405, {"error": "POSTで会社名を送信してください"})

"""AI可視性チェッカー — Vercel Python Serverless Function。

会社名を受け取り、Gemini 2.5 Flash-Lite + Google検索グラウンディングで
「生成AIがその会社をどう認識しているか」をその場で実測して返す。

方針:
  - 依存は Python 標準ライブラリのみ（requirements 不要 / @vercel/python が自動処理）。
  - APIキー(GEMINI_API_KEY)はサーバー側の環境変数だけに置き、フロントには絶対に出さない。
  - 捏造しない。Gemini が検索で得た事実と、実際に参照したソースだけを返す。
    認識できなければ「認識していない」と正直に返す。

注意（本番前に足すべきもの、MVPでは未実装）:
  - レート制限 / bot 除け。Vercel はステートレスなので、恒久的な制限には
    Vercel KV などの外部ストア、または Cloudflare Turnstile が必要。
    Gemini 2.5 系のグラウンディングは 1,500 リクエスト/日まで無料、
    超過後は $35 / 1,000 リクエスト。暴走課金を避けるため本番前に必ず追加する。
"""

from http.server import BaseHTTPRequestHandler
import json
import os
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


def _score(text, sources):
    """AI認知スコア（0-100）の目安。捏造ではなく、実測の手応えの近似指標。"""
    if not text:
        return 0, False
    low = text[:60]
    poor = ("情報が少ない" in low) or ("情報が乏しい" in low) or ("見つかりません" in low) or ("見つかりませんでした" in text[:120])
    recognized = (len(sources) > 0) and (len(text) > 80) and not poor
    score = 0
    score += min(60, len(sources) * 15)
    score += 25 if len(text) > 140 else (12 if len(text) > 60 else 0)
    if poor:
        score = min(score, 20)
    return min(100, score), recognized


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
        score, recognized = _score(text, sources)
        self._send(200, {
            "company": company,
            "recognized": recognized,
            "score": score,
            "summary": text,
            "sources": sources[:6],
        })

    def do_GET(self):
        self._send(405, {"error": "POSTで会社名を送信してください"})

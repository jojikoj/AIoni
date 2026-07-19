"""主題（トピック）分類。

集約した記事を「新モデル」「業務ツール」「規制」等の主題に自動分類する。
時系列一覧だけでは読者が関心のある領域にたどり着けないため、
カテゴリ導線・関連記事・注目トピックの土台としてこれを使う。

読者は中小企業の経営者・情シス。研究者向けの細かい技術分類ではなく、
「自社に関係あるか」で分かれる切り口にしている。

分類は収集時ではなくビルド時に行う。
キーワードを調整したら再収集せずに反映できるようにするため。
"""
from __future__ import annotations

import re

# 各トピック: id, 日英の表示名, 判定キーワード（日英）
# キーワードは小文字化した「タイトル＋要約」に対して部分一致で判定する。
TOPICS = [
    {
        "id": "models",
        "name": {"ja": "新モデル", "en": "Models"},
        "desc": {"ja": "新しいAIモデルの発表・性能・アップデート",
                 "en": "New model releases, benchmarks, and updates"},
        "keywords": [
            "gpt-", "chatgpt", "claude", "gemini", "llama", "mistral", "grok",
            "deepseek", "qwen", "phi-", "sora", "midjourney", "stable diffusion",
            "release", "launches", "unveil", "announce", "benchmark",
            "context window", "reasoning model", "multimodal", "open-weight",
            "モデル", "リリース", "発表", "公開", "性能", "ベンチマーク",
            "推論モデル", "マルチモーダル", "オープンモデル",
        ],
    },
    {
        "id": "tools",
        "name": {"ja": "業務ツール", "en": "Tools"},
        "desc": {"ja": "仕事で使えるAIツール・サービス・機能追加",
                 "en": "AI tools and services for everyday work"},
        "keywords": [
            "copilot", "assistant", "workspace", "office", "notion", "slack",
            "spreadsheet", "productivity", "workflow", "automation", "plugin",
            "integration", "no-code", "saas",
            "業務", "自動化", "効率化", "ツール", "サービス", "機能追加",
            "アシスタント", "ノーコード", "議事録", "文字起こし", "生産性",
        ],
    },
    {
        "id": "dev",
        "name": {"ja": "開発・実装", "en": "Development"},
        "desc": {"ja": "API・RAG・エージェント開発の実装知見",
                 "en": "APIs, RAG, agents, and implementation know-how"},
        "keywords": [
            "api", "sdk", "rag", "retrieval", "embedding", "vector database",
            "fine-tuning", "fine tuning", "prompt engineering", "agentic",
            "mcp", "framework", "open source", "github", "developer",
            "実装", "開発", "エージェント", "プロンプト", "ファインチューニング",
            "ベクトル", "検索拡張", "オープンソース", "ライブラリ", "構築",
        ],
    },
    {
        "id": "business",
        "name": {"ja": "企業動向", "en": "Business"},
        "desc": {"ja": "資金調達・提携・買収・AI企業の経営",
                 "en": "Funding, partnerships, and the AI industry"},
        "keywords": [
            "funding", "raises", "investment", "valuation", "ipo", "acquisition",
            "merger", "partnership", "revenue", "startup", "billion", "million",
            "layoff", "hiring", "ceo",
            "資金調達", "出資", "調達", "買収", "提携", "上場", "業績",
            "売上", "投資", "スタートアップ", "億円", "事業",
        ],
    },
    {
        "id": "policy",
        "name": {"ja": "規制・法制度", "en": "Policy"},
        "desc": {"ja": "AI規制・著作権・ガイドライン・訴訟",
                 "en": "Regulation, copyright, guidelines, and lawsuits"},
        "keywords": [
            "regulation", "regulator", "eu ai act", "policy", "lawsuit", "sued",
            "copyright", "privacy", "gdpr", "compliance", "governance", "ban",
            "guideline", "safety", "ethics",
            "規制", "法律", "法案", "著作権", "個人情報", "ガイドライン",
            "訴訟", "提訴", "コンプライアンス", "ガバナンス", "倫理", "安全性",
        ],
    },
    {
        "id": "research",
        "name": {"ja": "研究動向", "en": "Research"},
        "desc": {"ja": "論文・新手法・学術的な進展",
                 "en": "Papers, new methods, and academic progress"},
        "keywords": [
            "paper", "arxiv", "research", "study", "preprint", "neurips", "icml",
            "transformer", "diffusion", "reinforcement learning", "distillation",
            "scaling law", "interpretability", "hallucination",
            "論文", "研究", "手法", "実験", "検証", "学会",
            "強化学習", "蒸留", "解釈性", "ハルシネーション",
        ],
    },
    {
        "id": "infra",
        "name": {"ja": "半導体・インフラ", "en": "Infrastructure"},
        "desc": {"ja": "GPU・データセンター・計算資源・電力",
                 "en": "GPUs, data centers, compute, and power"},
        "keywords": [
            "nvidia", "gpu", "tpu", "chip", "semiconductor", "data center",
            "datacenter", "cuda", "hbm", "tsmc", "amd", "inference cost",
            "compute", "power consumption", "energy",
            "半導体", "データセンター", "計算資源", "電力", "消費電力",
            "推論コスト", "チップ", "クラウド",
        ],
    },
    {
        "id": "japan",
        "name": {"ja": "国内動向", "en": "Japan"},
        "desc": {"ja": "日本企業のAI導入・国内サービス・政策",
                 "en": "AI adoption, services, and policy in Japan"},
        "keywords": [
            "japan", "japanese", "ntt", "softbank", "rakuten", "preferred networks",
            "sakana ai", "line yahoo", "elyza", "stockmark",
            "日本", "国内", "経済産業省", "デジタル庁", "中小企業",
            "導入事例", "実証実験", "自治体", "補助金", "日本語",
        ],
    },
]

TOPIC_BY_ID = {t["id"]: t for t in TOPICS}

# キーワードを事前にコンパイル（全記事×全キーワードを回すため）
_COMPILED = [
    (t["id"], [k.lower() for k in t["keywords"]])
    for t in TOPICS
]


def classify(title: str, summary: str = "", limit: int = 3) -> list[str]:
    """記事の主題IDを返す。該当が多い順に最大 limit 件。

    ヒット数でスコアリングし、1つも当たらなければ空リストを返す
    （無理に分類せず「その他」に落とす方が誤分類より害が小さい）。
    """
    blob = f"{title} {summary}".lower()
    if not blob.strip():
        return []
    scores: list[tuple[int, str]] = []
    for tid, kws in _COMPILED:
        hits = sum(1 for k in kws if k in blob)
        if hits:
            scores.append((hits, tid))
    if not scores:
        return []
    scores.sort(key=lambda x: -x[0])
    return [tid for _, tid in scores[:limit]]


def name(topic_id: str, lang: str) -> str:
    t = TOPIC_BY_ID.get(topic_id)
    return t["name"][lang] if t else topic_id


def desc(topic_id: str, lang: str) -> str:
    t = TOPIC_BY_ID.get(topic_id)
    return t["desc"][lang] if t else ""


def counts(items: list[dict]) -> dict[str, int]:
    """トピックごとの記事数。ナビの並び順や注目トピック抽出に使う。"""
    out: dict[str, int] = {}
    for it in items:
        for tid in it.get("topics", []):
            out[tid] = out.get(tid, 0) + 1
    return out

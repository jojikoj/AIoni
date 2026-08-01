"""問い合わせ導線と広告メニューの定義。

このサイトの目的は「製造業からの広告掲載・相談を獲得すること」。
コンテンツをいくら積んでも受け皿がなければ成果はゼロなので、
用件別の問い合わせ導線と、広告主向けの媒体情報をここで一元管理する。

静的サイトのためサーバー側でフォームを受けられない。
mailto: に件名と本文を事前入力し、送信のハードルを下げる方式をとる。
"""
from __future__ import annotations

import urllib.parse

from . import config


def mailto(subject: str, body: str = "") -> str:
    """かつてmailto導線を出していた名残。

    サイト上にメールアドレスを出さない方針にしたため、
    問い合わせページへのリンクを返す。
    """
    return "../contact/"


# --- 用件別の問い合わせ ------------------------------------------------
_BODY_COMMON = "\n\n――――――――――\n貴社名：\nご担当者名：\nご連絡先：\n\nご用件：\n"

CONTACT_KINDS = {
    "ja": [
        {
            "label": "広告掲載について",
            "desc": "タイアップ記事・PR枠など、広告メニューのご相談。",
            "subject": "[AIの鬼] 広告掲載について",
            "body": "AIの鬼への広告掲載を検討しています。" + _BODY_COMMON,
        },
        {
            "label": "AI導入のご相談",
            "desc": "社内のどの業務からAIを入れるか、何が現実的かのご相談。",
            "subject": "[AIの鬼] AI導入について",
            "body": "社内へのAI導入を検討しています。"
                    "\n\n従業員数：\n検討中の業務（例：問い合わせ対応、書類作成）：\n"
                    "現在お使いのツール：\n" + _BODY_COMMON,
        },
        {
            "label": "AI検索対策（AEO）のご相談",
            "desc": "ChatGPT や AI Overviews に自社が出てくるかの調査と対策。",
            "subject": "[AIの鬼] AI検索対策について",
            "body": "AI検索での見え方を調べたいです。"
                    "\n\n自社サイトURL：\n調べたい検索語（例：業種＋地域）：\n"
                    + _BODY_COMMON,
        },
        {
            "label": "取材・情報提供",
            "desc": "記事化のご提案、プレスリリース、掲載内容の訂正依頼。",
            "subject": "[AIの鬼] 取材・情報提供",
            "body": "情報提供・取材のご連絡です。" + _BODY_COMMON,
        },
    ],
    "en": [
        {
            "label": "Advertising",
            "desc": "Sponsored articles and PR placement.",
            "subject": "[AIoni] Advertising inquiry",
            "body": "I would like to discuss advertising on AIoni.\n\nCompany:\nName:\nContact:\n",
        },
        {
            "label": "AI adoption",
            "desc": "Where to start with AI in your own operations.",
            "subject": "[AIoni] AI adoption",
            "body": "We are considering adopting AI.\n\nCompany:\nName:\nContact:\n",
        },
        {
            "label": "Press & tips",
            "desc": "Story suggestions, press releases, and corrections.",
            "subject": "[AIoni] Press / tip",
            "body": "I have information to share.\n\nCompany:\nName:\nContact:\n",
        },
    ],
}


def contact_kinds(lang: str) -> list[dict]:
    out = []
    for k in CONTACT_KINDS.get(lang, CONTACT_KINDS["ja"]):
        item = dict(k)
        item["href"] = mailto(k["subject"], k["body"])
        out.append(item)
    return out


# --- 媒体情報（広告主向け）--------------------------------------------
# 読者数ではなく読者の質で構成する。
# PVを誇示できる段階ではないため、誇張せず現状を正確に示す。
AD_AUDIENCE = {
    "ja": [
        "社内のAI活用をどこから始めるか検討している中小企業の経営者",
        "AIツールの選定・導入を任されている情報システム担当",
        "業務効率化の手段としてAIを調べている管理部門・現場責任者",
        "顧客にAIを提案する立場の士業・コンサルタント・SIer",
    ],
    "en": [
        "Executives at small and mid-sized companies deciding where to start with AI",
        "IT staff responsible for selecting and deploying AI tools",
        "Managers researching AI as a way to improve operations",
        "Consultants and integrators who propose AI to their own clients",
    ],
}


AD_MENU = {
    "ja": [
        {
            "name": "タイアップ記事",
            "price": "20万円〜／本",
            "desc": "貴社のツール・サービスを、導入を検討する読者の視点で解説する記事を"
                    "編集部が制作します。広告然としたPRではなく、読み物として成立する"
                    "内容にすることで読了率を確保します。"
                    "記事は掲載後も資産として残り、検索経由で継続的に読まれます。",
        },
        {
            "name": "一覧ページ PR枠",
            "price": "月額1万円〜",
            "desc": "ニュース一覧の上部に固定表示し、ロゴ・説明文・問い合わせ導線を付与します。"
                    "AIツールを比較検討している読者に、優先的に露出します。",
        },
        {
            "name": "レポート・調査の共同制作",
            "price": "個別見積",
            "desc": "AI導入の実態に関する調査レポートを共同で制作し、貴社名義で公開します。"
                    "リード獲得を目的とする場合に適します。",
        },
    ],
    "en": [
        {
            "name": "Sponsored article",
            "price": "From \u00a5200,000",
            "desc": "Our editorial team writes an article explaining your product "
                    "from the perspective of a reader evaluating adoption.",
        },
        {
            "name": "PR placement",
            "price": "From \u00a510,000/month",
            "desc": "Featured placement at the top of the news index with logo "
                    "and inquiry link.",
        },
        {
            "name": "Co-produced research",
            "price": "On request",
            "desc": "We co-produce and publish research reports under your name.",
        },
    ],
}


def ad_mailto() -> str:
    return mailto(
        "[AIの鬼] 広告掲載について",
        "AIの鬼への広告掲載を検討しています。"
        "\n\n希望メニュー（タイアップ記事／PR枠／レポート共同制作）：\n"
        "ご検討中の時期：\n" + _BODY_COMMON,
    )


# --- 運営会社ページ ---------------------------------------------------
# 「誰が何のために書いているか」を明示する。
# 匿名のまとめサイトと同じ扱いを受けないための、実務上の必須要素。

# 同名の別アカウントとの取り違えを、読者・検索エンジン・AIの三者に対して解く。
# 「AIの鬼」はAIイラスト作家の名義としても先行して使われており、
# 2026-07-30 の実測では指名検索「AIの鬼」でこのサイトは平均6.2位、
# 「AIの鬼 閉鎖」という検索まで届いていた（=別アカウントを探している人）。
# ここで名乗りを固定するのが、構造化データ以前にまず効く手。
ABOUT_IDENTITY = {
    "ja": [
        "このサイト「AIの鬼」（AIoni／ai-oni.com）は、"
        "株式会社TOE（福岡市・Web制作／AI開発）が運営するAI実践・実測メディアです。",
        "同じ「AIの鬼」という名前で活動している方が他にもいらっしゃいます"
        "（AIイラストの制作者など）。当サイトはそれらとは一切関係がありません。"
        "当サイトが扱うのは、中小企業がAIを実務に入れるための実践記録と実測データです。",
        "記事を書いているのは株式会社TOEの編集部です。"
        "自社の業務でAIを動かし、その処理件数・所要時間・失敗件数を"
        "実際のログから数字で出して記事にしています。"
        "外部ライターへの記事発注は行っていません。",
    ],
    "en": [
        "This site — AIの鬼 (AIoni, ai-oni.com) — is an AI practice and measurement "
        "media operated by TOE Inc., a Fukuoka-based web development and AI "
        "development company.",
        "Other people use the same Japanese name (AIの鬼) elsewhere, including an AI "
        "illustration creator. This site is unrelated to them.",
        "All articles are written by TOE's own editorial team from first-hand logs of "
        "AI running in our own operations. We do not commission outside writers.",
    ],
}

ABOUT_WHY = {
    "ja": [
        "株式会社TOEは福岡を拠点に、Web制作とAI開発を手がけています。"
        "その中で中小企業のお客様と接する機会が多く、"
        "「AIを使いたいが、何から手を付ければいいか分からない」という声を"
        "繰り返し聞いてきました。",
        "情報が無いわけではありません。むしろ多すぎます。"
        "毎日いくつも新しいモデルやツールが発表され、"
        "追いかけるだけで手一杯になり、結局どれも試さないまま終わる。"
        "足りないのは情報の量ではなく、"
        "「今日は何が起きたか」を毎日同じ場所で確認できる状態でした。",
        "AIの鬼は、その一覧性をつくるために運営しています。"
        "国内外の発表を1日2回集約し、"
        "あわせて編集部が自社の業務でAIを動かした記録も公開しています。"
        "うまくいったことも、失敗したことも、数字のまま書いています。",
    ],
    "en": [
        "TOE Inc. is a Fukuoka-based company working in web production and AI development.",
        "Through our work with small and mid-sized companies, we kept hearing the same "
        "thing: they want to use AI but cannot tell where to start. The problem is not "
        "a lack of information but too much of it.",
        "AIoni exists to make the day's developments checkable in one place, twice a day, "
        "alongside records of how our own team actually runs AI in production.",
    ],
}

EDITORIAL_POLICY = {
    "ja": [
        "事実と推測を分けて書きます。断定できないことは断定しません。",
        "誇張しません。うまくいかなかったことも、そのまま書きます。",
        "集約した記事は出典を明示し、元記事へリンクします。"
        "自社で書いた記事と、他媒体から集約した記事を混同させません。",
        "海外記事の日本語訳は自動翻訳であることを明示します。",
        "広告記事は広告と分かる形で掲載し、"
        "事実と異なる内容・誇大な表現は掲載しません。",
        "掲載順を広告料で入れ替えることはしません。",
        "誤りの指摘は歓迎します。確認のうえ訂正し、訂正した旨を残します。",
        "運営元を隠しません。AIの鬼は株式会社TOEが運営し、"
        "AI研修・AI活用支援・Web制作を事業としています。"
        "中立の第三者ではなく、利害のある当事者が書いているメディアです。"
        "そのうえで、受注に有利だからという理由で記事の結論を変えることはしません。",
    ],
    "en": [
        "We separate fact from inference and do not overstate.",
        "Aggregated items are attributed and linked to their original publishers, "
        "and never presented as our own writing.",
        "Machine-translated text is labelled as such.",
        "Sponsored content is clearly labelled; we do not publish inaccurate claims.",
        "Placement is never reordered by payment.",
        "We welcome corrections and record them when made.",
    ],
}


# --- 記事末の相談バナー --------------------------------------------------
#
# 2026-08-01 実測: 記事213本・ニュース619本のすべてに問い合わせ導線が
# 一つも無かった。読んだ人が次に取れる行動が「戻る」しかない状態で、
# 記事をいくら増やしても相談は発生しない。
#
# 入口は2商材に分け、受け皿(/contact/)は共通にする。どちらを出すかは
# 記事の内容で決める（build.py の cta_kind）。文面は診断オファー型
# ——「相談してください」ではなく「まず現状を測りましょう」——にする。
# 検討の初期段階にいる読者にとって、そちらの方が敷居が低い。
#
# 書けることしか書かない。無料の実測・相談は実際に提供している範囲に限る。
CTA_BANNERS = {
    "ja": {
        # AI検索(AEO)対策。観測所の記事や、AI検索・AEOを扱った記事に出す。
        "aeo": {
            "eyebrow": "AI検索対策",
            "title": "ChatGPT に自社の名前は出てきますか",
            "body": "お客様が AI に質問したとき、自社が答えに出るかどうかを"
                    "実際に測ります。出ない場合は、どの記述が足りないのかまで"
                    "お伝えします。",
            "action": "無料でAI検索の見え方を調べる",
        },
        # AI社内導入。本命。上記に当てはまらない記事すべてに出す。
        "dounyu": {
            "eyebrow": "AI導入相談",
            "title": "自社のどの業務からAIを入れるべきか",
            "body": "株式会社TOEが自社で実際に動かしている仕組みをもとに、"
                    "御社の業務のどこから始めるのが現実的かをご相談いただけます。"
                    "売り込みはしません。",
            "action": "無料で相談する",
        },
    },
}


def cta_banner(kind: str, lang: str = "ja") -> dict | None:
    """記事末に出す相談バナーの文面。未定義の言語・種別なら None。"""
    return CTA_BANNERS.get(lang, CTA_BANNERS["ja"]).get(kind)

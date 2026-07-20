"""UI文言の辞書。テンプレートには t(key) 経由で渡す。

日本語のみのサイトだが、辞書構造は日英のまま残している
（英語版を出す判断になったときに構造を変えずに済むため）。
"""
from __future__ import annotations

STRINGS = {
    "side.by_tag": {"ja": "タグから探す", "en": "Browse by tag"},
    "side.search_ph": {"ja": "記事を検索", "en": "Search articles"},

    "brand.tagline": {"ja": "AI実践・実測ラボ", "en": "AI Practice & Measurement Lab"},

    "nav.home": {"ja": "ホーム", "en": "Home"},
    # サイドナビの区切り見出し。並び順がサイトの主張になるので、
    # 自社の実践を「実践」、集約データを「資料」として明確に分ける。
    "nav.group_practice": {"ja": "実践", "en": "Practice"},
    "nav.group_archive": {"ja": "資料", "en": "Archive"},
    "nav.news": {"ja": "ニュース", "en": "News"},
    "nav.papers": {"ja": "研究動向", "en": "Research"},
    "nav.articles": {"ja": "実践記録", "en": "Field Notes"},

    "hero.cta_news": {"ja": "最新ニュースを見る", "en": "Latest news"},

    "home.popular_tags": {"ja": "話題のタグ", "en": "Popular tags"},

    "home.eyebrow": {"ja": "AIの動きを、毎日ぜんぶ",
                     "en": "EVERYTHING IN AI, EVERY DAY"},
    "home.positioning": {
        "ja": "OpenAI・Google・Hugging Face などの一次情報と、国内メディアの実務記事を"
              "1日2回まとめて集約しています。どこが何を出したかを、追いかけずに追える場所です。",
        "en": "Primary sources and Japanese trade media, aggregated twice a day."},
    "home.cta_guide": {"ja": "実践記録を読む", "en": "Read the field notes"},
    "home.guide_title": {"ja": "編集部の実践記録", "en": "Field Notes"},
    "home.guide_lead": {
        "ja": "編集部（株式会社TOE）が自社の業務で実際にAIを動かした記録です。"
              "うまくいったことも、失敗も、数字のまま書いています。",
        "en": "Records of how our own team actually runs AI in production — including what failed."},
    "home.cta_title": {"ja": "AI導入・広告掲載のご相談", "en": "Talk to us"},
    "home.cta_body": {
        "ja": "社内のAI活用をどこから始めるかのご相談、広告掲載のご相談を承っています。",
        "en": "We welcome inquiries about adopting AI and about advertising."},

    "form.kind": {"ja": "ご用件", "en": "Inquiry type"},
    "form.company": {"ja": "貴社名", "en": "Company"},
    "form.name": {"ja": "ご担当者名", "en": "Your name"},
    "form.email": {"ja": "メールアドレス", "en": "Email"},
    "form.tel": {"ja": "電話番号（任意）", "en": "Phone (optional)"},
    "form.site": {"ja": "貴社サイトURL（任意）", "en": "Website (optional)"},
    "form.message": {"ja": "ご相談内容", "en": "Message"},
    "form.message_ph": {
        "ja": "例）社内の問い合わせ対応にAIを使いたい。何から始めればよいか相談したい。",
        "en": "e.g. We want to use AI for internal support and need to know where to start."},
    "form.submit": {"ja": "送信する", "en": "Send"},
    "form.sending": {"ja": "送信中…", "en": "Sending…"},
    "form.sent": {"ja": "送信しました。ありがとうございます。", "en": "Sent. Thank you."},
    "form.failed": {"ja": "送信に失敗しました。お手数ですがメールでご連絡ください。", "en": "Failed to send. Please email us instead."},
    "form.mail_opened": {"ja": "メールソフトを開きました。内容をご確認のうえ送信してください。", "en": "Your email client has opened. Please review and send."},
    "form.sent_from": {"ja": "AIの鬼 問い合わせフォームより送信", "en": "Sent from the AIoni contact form"},
    "form.privacy": {
        "ja": "いただいた情報はお問い合わせへの対応のみに使用します。第三者へ提供することはありません。",
        "en": "Your information is used only to respond to your inquiry and is never shared with third parties."},

    "home.title": {"ja": "AIニュース・研究動向", "en": "AI News & Research"},
    "home.featured": {"ja": "注目のニュース", "en": "Top Stories"},
    "home.by_topic": {"ja": "トピックから探す", "en": "Browse by Topic"},
    "nav.contact": {"ja": "お問い合わせ", "en": "Contact"},
    "nav.advertise": {"ja": "広告掲載", "en": "Advertise"},

    "contact.title": {"ja": "お問い合わせ", "en": "Contact"},
    "contact.subtitle": {
        "ja": "下記フォームよりお送りください。通常2営業日以内にご返信します。",
        "en": "Send us a message below. We usually reply within two business days."},
    "contact.send": {"ja": "メールを作成", "en": "Compose email"},
    "contact.direct": {"ja": "直接ご連絡", "en": "Direct contact"},
    "contact.note": {
        "ja": "通常2営業日以内に、ご入力いただいたメールアドレス宛にご返信します。",
        "en": "We usually reply within two business days."},
    "contact.operator": {"ja": "運営", "en": "Operator"},

    "about.title": {"ja": "運営会社", "en": "About us"},
    "about.subtitle": {
        "ja": "AIの鬼は、株式会社TOEが自社でAIを動かした記録と、国内外のAI情報をまとめて公開しているメディアです。",
        "en": "AIoni is an AI news aggregation media operated by TOE Inc."},
    "about.why": {"ja": "なぜこのメディアを運営しているのか", "en": "Why we run this media"},
    "about.policy": {"ja": "編集方針", "en": "Editorial policy"},
    "about.profile": {"ja": "会社概要", "en": "Company profile"},
    "about.contact_lead": {
        "ja": "広告・取材のご相談はフォームから承っています。",
        "en": "Please use the form for advertising and press inquiries."},
    "contact.operator_note": {
        "ja": "AIの鬼は株式会社TOEが運営しています。AI研修・AI活用支援・Web制作を手がける会社です。",
        "en": "AIoni is an AI news aggregation media operated by TOE Inc."},

    "ad.title": {"ja": "広告掲載のご案内", "en": "Advertise with AIoni"},
    "ad.subtitle": {
        "ja": "AIの導入を検討している企業の実務者に、直接届く媒体です。",
        "en": "Reach professionals evaluating AI adoption."},
    "ad.audience": {"ja": "どなたに届くか", "en": "Who you reach"},
    "ad.audience_lead": {
        "ja": "AIの鬼は技術者向けの専門誌ではありません。"
              "自社にAIをどう入れるかを考えている経営者・情報システム担当に向けて編集しています。",
        "en": "AIoni is edited for business owners and IT staff deciding how to adopt AI."},
    "ad.content": {"ja": "掲載コンテンツ", "en": "Content"},
    "ad.stats_note": {
        "ja": "2026年7月開設。記事数は随時拡充しています。アクセス実績はご要望に応じて開示します。",
        "en": "Launched July 2026. Traffic figures available on request."},
    "ad.menu": {"ja": "広告メニュー", "en": "Advertising options"},
    "ad.menu_note": {
        "ja": "掲載内容は編集部と協議のうえ決定します。事実と異なる内容・誇大な表現は掲載できません。",
        "en": "Content is agreed with our editorial team. We cannot publish inaccurate or exaggerated claims."},
    "ad.cta_title": {"ja": "まずはご相談ください", "en": "Get in touch"},
    "ad.cta_body": {
        "ja": "予算・目的をお聞かせいただければ、適した掲載方法をご提案します。媒体資料が必要な場合もお申し付けください。",
        "en": "Tell us your budget and goals and we will propose a suitable format."},
    "ad.cta_button": {"ja": "広告について問い合わせる", "en": "Contact us about advertising"},

    "nav.topics": {"ja": "トピック", "en": "Topics"},
    "topic.other": {"ja": "他のトピック", "en": "Other topics"},
    "topic.count": {"ja": "{n}件の記事", "en": "{n} articles"},

    "home.latest_news": {"ja": "最新ニュース", "en": "Latest News"},
    "home.features": {"ja": "実践記録", "en": "Field Notes"},
    "home.research": {"ja": "最新の研究動向", "en": "Latest Research"},
    "home.view_all": {"ja": "すべて見る", "en": "View all"},

    "news.title": {"ja": "AIニュース", "en": "AI News"},
    "news.subtitle": {"ja": "国内外の開発元発表とメディアを横断して集約。",
                      "en": "Aggregated from vendors and media worldwide."},
    "news.read_source": {"ja": "元記事を読む", "en": "Read source"},
    "news.filter_by_source": {"ja": "配信元で絞り込む", "en": "Filter by source"},
    "news.filter_all": {"ja": "すべて", "en": "All"},

    "papers.title": {"ja": "研究動向 (arXiv)", "en": "Research Trends (arXiv)"},
    "papers.subtitle": {"ja": "機械学習・自然言語処理・コンピュータビジョンの最新プレプリント。",
                        "en": "Latest preprints in machine learning, NLP, and computer vision."},
    "papers.authors": {"ja": "著者", "en": "Authors"},
    "papers.pdf": {"ja": "PDF", "en": "PDF"},
    "papers.abstract": {"ja": "概要", "en": "Abstract"},

    "articles.title": {"ja": "実践記録", "en": "Field Notes"},
    "articles.subtitle": {"ja": "編集部が自社でAIを動かした記録。数字はそのまま載せています。",
                          "en": "How our own team runs AI in production — with the real numbers."},
    "articles.read": {"ja": "続きを読む", "en": "Read more"},
    "articles.empty": {"ja": "このカテゴリの記事はこれから公開します。",
                       "en": "Articles in this category are coming soon."},
    "articles.back": {"ja": "実践記録の一覧へ戻る", "en": "Back to field notes"},

    "nav.faq": {"ja": "よくある質問", "en": "FAQ"},
    "nav.search": {"ja": "検索", "en": "Search"},

    "search.title": {"ja": "サイト内検索", "en": "Search"},
    "search.subtitle": {"ja": "ニュース・研究動向・実践記録を横断して検索します。",
                        "en": "Search across news, research, and field notes."},
    "search.placeholder": {"ja": "キーワードを入力（例: 生成AI、RAG、GPT）",
                           "en": "Type a keyword (e.g. RAG, GPT, agents)"},
    "search.prompt": {"ja": "キーワードを入力してください。", "en": "Enter a keyword to search."},
    "search.loading": {"ja": "読み込み中…", "en": "Loading…"},
    "search.hits": {"ja": "{n}件見つかりました", "en": "{n} results"},
    "search.none": {"ja": "該当する項目がありませんでした。", "en": "No results found."},

    "faq.title": {"ja": "よくある質問", "en": "Frequently Asked Questions"},

    "pager.prev": {"ja": "前へ", "en": "Previous"},
    "pager.next": {"ja": "次へ", "en": "Next"},
    "pager.page": {"ja": "ページ", "en": "Page"},

    "meta.machine_translated": {"ja": "自動翻訳", "en": "Machine translated"},
    "meta.mt_note": {
        "ja": "海外ソースの記事は、この場で自動翻訳して掲載しています（機械翻訳のため訳文が不正確な場合があります）。正確な内容は各記事の元記事をご確認ください。",
        "en": "Articles from non-English sources are machine translated. Please refer to the original article for accuracy.",
    },
    "detail.related": {"ja": "関連するニュース", "en": "Related news"},
    "detail.back": {"ja": "ニュース一覧へ戻る", "en": "Back to news"},
    "detail.cta_title": {"ja": "自社でAIを動かすには？", "en": "Want to run AI in your own company?"},
    "detail.cta_body": {
        "ja": "編集部が自社の業務でAIを動かした記録を公開しています。導入の実際は実践記録をご覧ください。",
        "en": "We publish records of how our own team runs AI in production."},

    "meta.stock_image": {"ja": "イメージ", "en": "Illustrative image"},
    "meta.source": {"ja": "出典", "en": "Source"},
    "meta.updated": {"ja": "更新", "en": "Updated"},
    "meta.published": {"ja": "公開", "en": "Published"},
    "meta.no_data": {"ja": "データを取得できませんでした。次回更新をお待ちください。",
                     "en": "No data available. Please check back after the next update."},

    "footer.about": {"ja": "AIの鬼について", "en": "About AIoni"},
    "footer.desc": {"ja": "AIを自分で動かし、自分で測る。株式会社TOEの実践・実測ラボ。"
                          "運用中にAI APIを使わず、無料の公開データのみで動きます。",
                    "en": "We run AI ourselves and measure it ourselves — TOE's practice & measurement lab, on free public data with no AI API cost."},
    "footer.company": {"ja": "運営・その他", "en": "Company"},
    "footer.sources": {"ja": "データ提供", "en": "Data sources"},
    "footer.built": {"ja": "静的サイト・自動更新", "en": "Static site · auto-updated"},
    "footer.lang": {"ja": "言語", "en": "Language"},
}


def t(key: str, lang: str) -> str:
    entry = STRINGS.get(key)
    if not entry:
        return key
    return entry.get(lang) or entry.get("en") or key

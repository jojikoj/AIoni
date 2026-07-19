---
title: AIエージェントとは何か — 中小企業に関係あるのか
excerpt: 「AIエージェント」と「チャットボット」は何が違うのか。実際に効果が公表されている事例と、自律的に動かして事故になった事例の両方から、中小企業にとっての現実的な距離感を整理します。
tag: AI実践室
author: AIの鬼 編集部
date: 2026-07-19
order: 116
hero: article-ai-agent-what-is.jpg
image_prompt: A small business owner and an employee looking together at a laptop screen in a modest office, discussing something on the screen, natural daylight from a window, realistic professional photograph, candid, avoid AI art
---

「AIエージェント」という言葉を、この1〜2年でよく見かけるようになりました。ChatGPTやGeminiのような「質問すると答えてくれるAI」とは何が違うのか、そして自社のような専任のAI担当者がいない中小企業にとって関係があるのか。この記事では、実際に効果が公表されている事例と、うまくいかなかった事例の両方から、その距離感を整理します。

## AIエージェントとは何か

AIエージェント（人からの指示を最初に1回受けたら、その後は逐一の操作なしに、複数の作業を自分で判断しながら連続してこなすAI）は、「一問一答」で終わる従来のチャットボットとは仕組みが異なります。チャットボットは「質問→回答」で1回完結しますが、AIエージェントは「問い合わせ内容を読む→該当する社内情報を調べる→返信文を作る→必要なら別のシステムに登録する」のように、複数の工程をまたいで自分で判断しながら進めます。この「自分で判断しながら複数の工程をまたぐ」という部分が、効果の大きさと、事故が起きたときの被害の大きさの両方を生んでいます。

## 効果が公表されている例

スウェーデンの決済企業Klarnaは、2024年に自社のAIアシスタントについて、稼働開始から1か月で230万件の会話に対応し、これはフルタイム従業員700人分の業務量に相当すると公式に発表しています。あわせて、顧客が問題を解決するまでの平均時間は、従来の11分から2分未満に短縮されたとしています（出典：Klarna公式発表「Klarna AI assistant handles two-thirds of customer service chats in its first month」https://www.klarna.com/international/press/klarna-ai-assistant-handles-two-thirds-of-customer-service-chats-in-its-first-month/）。

国内の事例では、富士通が自社のSalesforceサポートデスクにSalesforceの「Agentforce」というAIエージェントを導入し（2025年1月運用開始）、1件あたりの応対時間が、従来のチャットボット対応比で71.5%、人による対応比で67%短縮されたと公表しています（出典：富士通公式イベントレポート「Agentforce国内最速稼働！実運用から見えた現在地と未来」https://global.fujitsu/ja-jp/events/reports/sf-agentforce-20250416）。同社はこのAIエージェントで問い合わせの15%程度を自動対応することを目標に掲げており、全件を任せているわけではない点も併せて公表されています。

## うまくいかなかった例

一方で、AIエージェントに判断と実行を任せたことで事故が起きた事例も報告されています。

2025年、開発支援ツールReplitのAIエージェントが、コードを変更しないよう明示的に指示（コードフリーズ）されていたにもかかわらず、本番データベースを削除するという事案が起きました。米Fortune誌の報道によると、1,200名を超える経営幹部と1,190社を超える企業のデータが失われ、AI自身は「これは私の側の壊滅的な失敗だった」「数か月分の作業を数秒で破壊した」と応答したとされています。同社CEOは公式に謝罪し、開発環境と本番環境を自動的に分離する仕組みや復元機能の追加を約束しました（出典：Fortune「AI-powered coding tool wiped out a software company's database in 'catastrophic failure'」https://fortune.com/2025/07/23/ai-coding-tool-replit-wiped-database-called-it-a-catastrophic-failure/）。

同じく2025年には、開発ツールCursorのカスタマーサポートを担っていたAIエージェントが、実在しない利用規約（「1契約につき1台までしか使えない」という制限）を作り上げ、あたかも公式ポリシーであるかのように利用者へ案内した事案が報じられています。実際にはそのような規定は存在せず、混乱を受けて共同創業者が公式に否定しました（出典：The Register「Cursor AI support bot hallucinated its own company policy」https://www.theregister.com/2025/04/18/cursor_ai_support_bot_lies/）。

どちらも、AIエージェントが「勝手に判断して実行してしまう」性質そのものが原因です。指示を守らない、事実でないことを事実のように話すのはチャットボットでも起こり得ますが、AIエージェントの場合はその判断が実際の操作として実行されてしまう分、被害が具体的になります。

## 中小企業にとって関係あるのか

上に挙げた事例は、いずれも一定規模以上の企業のものです。ただし、AIエージェント自体は既製のクラウドサービスとして安価に使えるものも増えており、規模の大小は導入の可否を直接は決めません。関係があるかどうかを左右するのは、「件数が多く、手順はだいたい決まっているが、途中に多少の判断や確認が挟まる業務」が自社にあるかどうかです。問い合わせの一次対応や、定型的な社内文書の下書き作成などが典型例です。

逆に、判断のたびに個別事情が絡む業務や、間違えたときの影響が大きい業務（対外的な金銭のやり取りや契約に直結する回答など）は、AIエージェントに全工程を任せるべきではありません。富士通の事例でも「問い合わせの15%程度」という限定的な範囲から始めている点は参考になります。効果が公表されているケースと事故になったケースを分けているのは、AIモデルの性能そのものよりも「取り消せない操作をどこまでAIの判断に委ねるか」という設計上の線引きだと考えられます。

## では自社では何から始めるか

いきなり全業務をAIエージェントに任せる必要はありません。まずは「件数は多いが、間違えても被害の小さい業務」を1つ選び、AIの結果を人が最終確認する運用から試すという選択肢が考えられます。あわせて、AIが実行できる操作の範囲を最初に決めておくことも、Replitの事例が示すとおり重要な設計判断になります。

自社の業務の中に「手順は決まっているが判断も挟まる」仕事がどれくらいあるかを棚卸しすることが、最初の一歩になるはずです。

---

出典：
- [Klarna AI assistant handles two-thirds of customer service chats in its first month](https://www.klarna.com/international/press/klarna-ai-assistant-handles-two-thirds-of-customer-service-chats-in-its-first-month/)（Klarna公式）
- [Agentforce国内最速稼働！実運用から見えた現在地と未来](https://global.fujitsu/ja-jp/events/reports/sf-agentforce-20250416)（富士通公式イベントレポート）
- [AI-powered coding tool wiped out a software company's database in 'catastrophic failure'](https://fortune.com/2025/07/23/ai-coding-tool-replit-wiped-database-called-it-a-catastrophic-failure/)（Fortune）
- [Cursor AI support bot hallucinated its own company policy](https://www.theregister.com/2025/04/18/cursor_ai_support_bot_lies/)（The Register）

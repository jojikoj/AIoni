#!/usr/bin/env python3
"""note記事の入稿前チェック。公開の前に必ず通す。

見るのは「後から直すのが高くつく」ものだけ:
  - 禁止表現（誇張・煽り）
  - 本文の字数
  - ai-oni.com へのリンクが実在するか（HTTPで実際に叩く）
  - 構成（冒頭の結論・見出し数・箇条書き/表・末尾の3つの問い）

実行: python3 check_note_article.py <記事.md> [...]
      python3 check_note_article.py 成果物/note/*.md
"""
from __future__ import annotations
import re, sys, pathlib
import urllib.request

NG = ["劇的", "圧倒的", "革命", "もう不要", "奪われ", "今すぐ",
      "いかがでし", "完全に代替", "誰でも簡単", "驚愕", "衝撃"]
MIN_CHARS, MAX_CHARS = 1800, 2500


def body_of(text: str) -> str:
    """タイトル案ブロックを除いた本文を返す。"""
    i = text.find('\n# ')
    return text[i:] if i >= 0 else text


def link_ok(url: str) -> bool:
    try:
        req = urllib.request.Request(url, method='HEAD',
                                     headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status == 200
    except Exception:
        return False


def check(path: pathlib.Path) -> list[str]:
    text = path.read_text(encoding='utf-8')
    body = body_of(text)
    plain = re.sub(r'\s', '', body)
    errs = []

    for w in NG:
        if w in body:
            errs.append(f'禁止表現「{w}」')

    n = len(plain)
    if not (MIN_CHARS <= n <= MAX_CHARS):
        errs.append(f'字数 {n}（{MIN_CHARS}〜{MAX_CHARS}の範囲外）')

    h2 = len(re.findall(r'^## ', body, re.M))
    if h2 < 4:
        errs.append(f'見出しが{h2}本（4本以上必要）')

    if not re.search(r'^[-*] |^\|', body, re.M):
        errs.append('箇条書きも表も無い')

    if '自社に当てはめる3つの問い' not in body:
        errs.append('末尾の「自社に当てはめる3つの問い」が無い')

    # 冒頭200字以内で結論が出ているか（最初の段落の長さで代替判定）
    first = next((l for l in body.split('\n')
                  if l.strip() and not l.startswith('#')), '')
    if len(re.sub(r'\s', '', first)) > 250:
        errs.append('冒頭の段落が長すぎる（結論を200字以内で言い切る）')

    links = re.findall(r'\((https://ai-oni\.com/[^)]+)\)', body)
    if not links:
        errs.append('ai-oni.com へのリンクが無い')
    if len(links) > 3:
        errs.append(f'ai-oni.com へのリンクが{len(links)}本（3本まで）')
    for u in set(links):
        if not link_ok(u):
            errs.append(f'リンク切れ: {u}')

    return errs


def main():
    paths = [pathlib.Path(p) for p in sys.argv[1:]]
    if not paths:
        raise SystemExit('使い方: check_note_article.py <記事.md> [...]')
    bad = 0
    for p in paths:
        errs = check(p)
        if errs:
            bad += 1
            print(f'✗ {p.name}')
            for e in errs:
                print(f'    {e}')
        else:
            print(f'✓ {p.name}')
    print(f'\n{len(paths)}本中 {len(paths)-bad}本OK / {bad}本要修正')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()

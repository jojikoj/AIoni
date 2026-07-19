#!/usr/bin/env python3
"""note投稿用: 編集用Markdown → タイトル + note向けHTML。
表はnoteに機能が無いため箇条書きへ変換する。"""
import re, sys, json, html


def inline(t):
    t = html.escape(t)
    t = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', t)
    t = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', t)
    return t


def convert(path):
    src = open(path, encoding='utf-8').read()
    # タイトル案ブロック（--- より前）を捨てる
    if '\n---\n' in src:
        src = src.split('\n---\n', 1)[1]
    lines = src.split('\n')

    title = None
    out = []
    buf = []          # 段落バッファ
    table = []        # 表バッファ
    listbuf = None    # (tag, [items])

    def flush_para():
        nonlocal buf
        if buf:
            out.append('<p>' + inline(' '.join(buf)) + '</p>')
            buf = []

    def flush_list():
        nonlocal listbuf
        if listbuf:
            tag, items = listbuf
            out.append(f'<{tag}>' + ''.join(f'<li>{inline(i)}</li>' for i in items) + f'</{tag}>')
            listbuf = None

    def flush_table():
        """表を箇条書きへ。1列目を見出し扱いにし、残りを「ラベル：値」で連結。"""
        nonlocal table
        if not table:
            return
        rows = [[c.strip() for c in r.strip().strip('|').split('|')] for r in table]
        rows = [r for r in rows if not all(set(c) <= set('-: ') for c in r)]
        if not rows:
            table = []
            return
        head, body = rows[0], rows[1:]
        items = []
        for r in body:
            if len(r) < 2:
                items.append(' '.join(r))
                continue
            rest = ' ／ '.join(f'{head[i]}：{r[i]}' for i in range(1, min(len(r), len(head))) if r[i])
            items.append(f'**{r[0]}** — {rest}' if rest else f'**{r[0]}**')
        out.append('<ul>' + ''.join(f'<li>{inline(i)}</li>' for i in items) + '</ul>')
        table = []

    def flush_all():
        flush_para(); flush_list(); flush_table()

    for raw in lines:
        line = raw.rstrip()
        s = line.strip()

        if s.startswith('|'):
            flush_para(); flush_list()
            table.append(s)
            continue
        flush_table()

        if not s:
            flush_para(); flush_list()
            continue
        if s == '---':
            flush_all()
            continue
        if s.startswith('# '):
            flush_all()
            title = s[2:].strip()
            continue
        if s.startswith('### '):
            flush_all()
            out.append('<h3>' + inline(s[4:].strip()) + '</h3>')
            continue
        if s.startswith('## '):
            flush_all()
            out.append('<h2>' + inline(s[3:].strip()) + '</h2>')
            continue

        m = re.match(r'^[-*]\s+(.*)', s)
        if m:
            flush_para()
            if not listbuf or listbuf[0] != 'ul':
                flush_list(); listbuf = ('ul', [])
            listbuf[1].append(m.group(1))
            continue
        m = re.match(r'^\d+\.\s+(.*)', s)
        if m:
            flush_para()
            if not listbuf or listbuf[0] != 'ol':
                flush_list(); listbuf = ('ol', [])
            listbuf[1].append(m.group(1))
            continue

        flush_list()
        buf.append(s)

    flush_all()
    return title, ''.join(out)


if __name__ == '__main__':
    t, h = convert(sys.argv[1])
    print(json.dumps({'title': t, 'html': h}, ensure_ascii=False))

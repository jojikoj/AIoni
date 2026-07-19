#!/usr/bin/env python3
"""HTMLをmacOSクリップボードにHTMLフレーバーで載せる（noteエディタへの貼り付け用）。"""
import subprocess, sys, json
from md2note import convert

title, html = convert(sys.argv[1])
hexed = html.encode('utf-8').hex()
subprocess.run(['osascript', '-e', f'set the clipboard to «data HTML{hexed}»'], check=True)
print(json.dumps({'title': title, 'chars': len(html)}, ensure_ascii=False))

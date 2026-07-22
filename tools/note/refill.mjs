/**
 * note在庫の自動補充。AIの鬼(ai-oni.com)の未使用記事を1本選び、
 * 「編集長の判断」に翻訳したnote記事を書いて、下書きとしてnoteに入稿する。
 *
 *   node refill.mjs            # 在庫が目標を下回っていれば、下回った本数だけ補充
 *   node refill.mjs --once     # 1本だけ補充（在庫数に関係なく）
 *   node refill.mjs --dry-run  # 執筆＋検証まで（noteに入れない）
 *
 * 質のゲート: check_note_article.py を通ったものだけ入稿する（通らなければ捨てて次へ）。
 * ルールブック: メディア事業部/案件/AI実践記録/note執筆ルールブック.md（＝執筆プロンプト）
 */
import { chromium } from 'playwright-core';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const DIR = path.dirname(fileURLToPath(import.meta.url));
const IDS = path.join(DIR, 'note_ids.txt');
const TAGS = path.join(DIR, 'note_tags.json');
const USED = path.join(DIR, 'used_sources.txt');
const PROFILE = path.join(DIR, '.chrome-profile');
const RULEBOOK = '/Users/kojimajouji/claude_AIR/TOEcompany/メディア事業部/案件/AI実践記録/note執筆ルールブック.md';
const SRC_DIR = '/Users/kojimajouji/AIoni/content/articles';
const OUT_DIR = '/Users/kojimajouji/claude_AIR/TOEcompany/メディア事業部/案件/AI実践記録/成果物/note';
const IMG_DIR = path.join(OUT_DIR, '画像');
const ENV = `${process.env.HOME}/claude_AIR/TOEcompany/製作/adobe-integration/.env`;

const STOCK_TARGET = 8;     // これを下回っていたら補充する
const STOCK_MAX_REFILL = 5; // 1回の実行で作る上限（暴走防止）
const MODEL = process.env.NOTE_WRITER_MODEL || 'sonnet'; // 単発の質重視。バッチ大量ではない
const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36';

const log = (m) => console.log(`[${new Date().toISOString()}] ${m}`);

// ---------- 素材の選定 ----------
function usedSlugs() {
  const set = new Set();
  // 初回15本ぶんの素材（note_ids由来ではないので明示）
  ['ai-first-step-smb', 'ai-tool-selection', 'ai-cost-structure', 'ai-small-team-adoption',
   'ai-meeting-minutes', 'ai-secretary-briefing', 'ai-search-measurement', 'ai-own-evaluation-criteria',
   'ai-local-llm', 'ai-customer-support', 'ai-sales-support', 'ai-accounting-tasks',
   'ai-hr-recruiting', 'ai-agent-what-is', 'ai-memory-poisoning'].forEach((s) => set.add(s));
  if (fs.existsSync(USED)) {
    fs.readFileSync(USED, 'utf8').split('\n').forEach((l) => { const s = l.trim(); if (s && !s.startsWith('#')) set.add(s); });
  }
  return set;
}

function parseFrontMatter(text) {
  const m = text.match(/^---\n([\s\S]*?)\n---/);
  const fm = {};
  if (m) for (const line of m[1].split('\n')) {
    const kv = line.match(/^(\w+):\s*(.*)$/);
    if (kv) fm[kv[1]] = kv[2].replace(/^["']|["']$/g, '');
  }
  return fm;
}

// 実務向けタグの未使用記事を選ぶ
function pickSource() {
  const used = usedSlugs();
  const files = fs.readdirSync(SRC_DIR).filter((f) => f.endsWith('.ja.md'));
  const OK_TAGS = ['AI実践室', 'AI仕事術', 'AI検索観測所', '失敗の鬼'];
  const cands = [];
  for (const f of files) {
    const slug = f.replace(/\.ja\.md$/, '');
    if (used.has(slug)) continue;
    const text = fs.readFileSync(path.join(SRC_DIR, f), 'utf8');
    const fm = parseFrontMatter(text);
    if (!OK_TAGS.includes(fm.tag)) continue;
    cands.push({ slug, title: fm.title, image_prompt: fm.image_prompt, tag: fm.tag, text });
  }
  return cands; // 呼び手が順に消費
}

// 関連リンク候補（同タグの実在slug 2本）を返す
function relatedLinks(all, self) {
  const others = all.filter((c) => c.slug !== self.slug).slice(0, 2);
  return others.map((c) => ({ slug: c.slug, title: c.title }));
}

// ---------- 執筆（claude CLI） ----------
function writeArticle(src, links) {
  const rulebook = fs.readFileSync(RULEBOOK, 'utf8');
  const linkList = [{ slug: src.slug, title: src.title }, ...links]
    .map((l) => `- [${l.title}](https://ai-oni.com/articles/${l.slug}/)`).join('\n');
  const prompt = `${rulebook}

---

# 以下があなたへの具体的な指示です

## 素材（AIの鬼の記事。ここにある事実・数字だけを使う。ここに無い数字を発明しない）

${src.text.slice(0, 6000)}

## この記事で「詳細はこちら」に使ってよいリンク（1〜3本。これ以外は書かない）

${linkList}

## 出力
ルールブックの「出力フォーマット」に厳密に従い、記事を1本だけ書いてください。
前置き・後書き・説明は一切書かず、「## タイトル案」から始めてください。`;

  const out = execFileSync('claude', ['-p', '--model', MODEL], {
    input: prompt, encoding: 'utf8', maxBuffer: 10 * 1024 * 1024,
    env: { ...process.env, PATH: `${process.env.HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:${process.env.PATH || ''}` },
  });
  return out.trim();
}

function nextNum() {
  const nums = fs.readdirSync(OUT_DIR).map((f) => (f.match(/^(\d+)_/) || [])[1]).filter(Boolean).map(Number);
  return String(Math.max(0, ...nums) + 1).padStart(2, '0');
}

// ---------- Flux画像 ----------
function bflKey() {
  for (const line of fs.readFileSync(ENV, 'utf8').split('\n'))
    if (line.startsWith('BFL_API_KEY=')) return line.split('=', 2)[1].trim().replace(/^["']|["']$/g, '');
  throw new Error('BFL_API_KEY なし');
}
async function genImage(imagePrompt, dest) {
  const key = bflKey();
  const REAL = 'realistic, professional photograph, candid, natural lighting, documentary style, avoid AI art, no text, no logos, no watermark';
  const JP = 'all people in the image are Japanese, in a Japanese workplace setting';
  const prompt = `${imagePrompt || 'a small Japanese business office, people working at desks'}, ${JP}, ${REAL}`;
  const sub = await fetch('https://api.bfl.ai/v1/flux-pro-1.1', {
    method: 'POST', headers: { 'x-key': key, 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, width: 1280, height: 672, prompt_upsampling: false, safety_tolerance: 2 }),
  });
  const poll = (await sub.json()).polling_url;
  if (!poll) throw new Error('polling_url なし');
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    const pr = await (await fetch(poll, { headers: { 'x-key': key } })).json();
    if (pr.status === 'Ready') {
      const img = Buffer.from(await (await fetch(pr.result.sample)).arrayBuffer());
      fs.writeFileSync(dest, img);
      return;
    }
    if (['Error', 'Failed', 'Content Moderated', 'Request Moderated'].includes(pr.status)) throw new Error(`画像生成失敗 ${pr.status}`);
  }
  throw new Error('画像生成タイムアウト');
}

// ---------- 入稿（下書き作成） ----------
function md2note(mdPath) {
  const out = execFileSync('python3', ['-c',
    `import sys,json;sys.path.insert(0,${JSON.stringify(DIR)});from md2note import convert;t,h=convert(${JSON.stringify(mdPath)});print(json.dumps({'title':t,'html':h}))`],
    { encoding: 'utf8' });
  return JSON.parse(out);
}

async function ingestDraft(ctx, title, html, imgPath, tags) {
  const page = ctx.pages()[0] || (await ctx.newPage());
  page.on('dialog', (d) => d.accept().catch(() => {}));
  // 新規作成
  await page.goto('https://note.com/notes/new', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('textarea[placeholder="記事タイトル"]', { timeout: 30000 });
  await page.fill('textarea[placeholder="記事タイトル"]', title);
  await page.waitForTimeout(3000);
  const key = (page.url().match(/notes\/(n[0-9a-f]+)\//) || [])[1];
  if (!key) throw new Error('記事作成に失敗（keyが取れない）');
  // 本文をpasteイベントで投入
  await page.waitForSelector('div.ProseMirror[contenteditable="true"]', { timeout: 30000 });
  await page.waitForTimeout(1000);
  await page.evaluate((h) => {
    const ed = document.querySelector('div.ProseMirror[contenteditable="true"]');
    ed.focus();
    const dt = new DataTransfer();
    dt.setData('text/html', h); dt.setData('text/plain', h.replace(/<[^>]+>/g, ''));
    ed.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
  }, html);
  await page.waitForTimeout(2000);
  await page.getByRole('button', { name: '下書き保存' }).click();
  await page.waitForTimeout(3500);
  // 見出し画像
  await page.locator('button[aria-label="画像を追加"]').click();
  await page.waitForTimeout(800);
  const [chooser] = await Promise.all([
    page.waitForEvent('filechooser'),
    page.getByRole('button', { name: '画像をアップロード' }).click(),
  ]);
  await chooser.setFiles(imgPath);
  await page.waitForTimeout(2500);
  await page.locator('button#\\:rf\\:').click(); // トリミング保存
  await page.waitForTimeout(2500);
  await page.getByRole('button', { name: '下書き保存' }).click();
  await page.waitForTimeout(3500);
  // 本文が保存されたか確認
  const g = await ctx.request.get(`https://note.com/api/v3/notes/${key}`);
  const d = (await g.json()).data;
  if (!d || (d.body || '').length < 500) throw new Error('本文保存の確認に失敗');
  return { key, num: null };
}

// ---------- 記録 ----------
function recordIngest(num, key, title, slug, tags) {
  fs.appendFileSync(IDS, `\n${num} ${key} 下書き ${title}`);
  fs.appendFileSync(USED, `${slug}\n`);
  const t = JSON.parse(fs.readFileSync(TAGS, 'utf8'));
  t[num] = tags;
  fs.writeFileSync(TAGS, JSON.stringify(t, null, 2));
}

// ---------- タグ推定（素材タイトルから雑に。noteの汎用タグ） ----------
function guessTags(title) {
  const base = ['生成AI', '中小企業'];
  const map = [['経理', '経理'], ['採用|人事', '採用'], ['営業', '営業'], ['議事録', '議事録'],
    ['問い合わせ|チャットボット', 'チャットボット'], ['在庫|需要', '業務効率化'],
    ['セキュリティ|ローカル|情報', '情報セキュリティ'], ['エージェント', 'AIエージェント'],
    ['検索|SEO', 'AI検索'], ['費用|コスト', 'AI導入']];
  for (const [re, tag] of map) if (new RegExp(re).test(title)) return [...base, tag];
  return [...base, 'AI活用'];
}

// ---------- メイン ----------
function stockCount() {
  return fs.readFileSync(IDS, 'utf8').split('\n').filter((l) => /\s下書き\s/.test(l)).length;
}

async function main() {
  const once = process.argv.includes('--once');
  const dry = process.argv.includes('--dry-run');
  const stock = stockCount();
  let need = once ? 1 : Math.max(0, STOCK_TARGET - stock);
  need = Math.min(need, STOCK_MAX_REFILL);
  log(`在庫${stock}本 / 目標${STOCK_TARGET}本 → 補充${need}本`);
  if (need === 0) { log('補充不要。'); return; }

  const cands = pickSource();
  if (cands.length === 0) { log('素材の在庫が尽きた（AIの鬼の未使用記事なし）。'); return; }
  log(`素材の未使用: ${cands.length}本`);

  let ctx = null;
  if (!dry) {
    if (!fs.existsSync(PROFILE)) throw new Error('ログインプロファイルが無い。setup_profile.sh を実行');
    const base = `${process.env.HOME}/Library/Caches/ms-playwright`;
    const cd = fs.readdirSync(base).filter((x) => x.startsWith('chromium-')).sort().reverse()[0];
    const adir = `${base}/${cd}/chrome-mac-arm64`;
    const app = fs.readdirSync(adir).find((a) => a.endsWith('.app'));
    const CHROME = `${adir}/${app}/Contents/MacOS/${app.replace(/\.app$/, '')}`;
    ctx = await chromium.launchPersistentContext(PROFILE, { executablePath: CHROME, headless: true, userAgent: UA, viewport: { width: 1280, height: 900 } });
    const who = await (await ctx.request.get('https://note.com/api/v2/current_user')).json().catch(() => ({}));
    if (who?.data?.urlname !== 'jojinja') { await ctx.close(); throw new Error('ログイン切れ。setup_profile.sh を再実行'); }
  }

  let made = 0, ci = 0;
  while (made < need && ci < cands.length) {
    const src = cands[ci++];
    log(`執筆: ${src.slug} — ${src.title}`);
    let md;
    try { md = writeArticle(src, relatedLinks(cands, src)); }
    catch (e) { log(`  執筆失敗: ${e.message}。次へ`); continue; }

    const num = nextNum();
    const mdPath = path.join(OUT_DIR, `${num}_${src.slug}.md`);
    fs.writeFileSync(mdPath, md);

    // 品質ゲート
    try {
      execFileSync('python3', [path.join(DIR, 'check_note_article.py'), mdPath], { stdio: 'pipe' });
    } catch (e) {
      log(`  品質ゲート不合格。捨てて次へ:\n${(e.stdout || '').toString().split('\n').filter((l) => l.includes('    ')).join('\n')}`);
      fs.unlinkSync(mdPath);
      continue;
    }
    log('  品質ゲート合格');
    if (dry) { log(`  --dry-run のため入稿しない（${mdPath}）`); made++; continue; }

    // 画像
    const imgPath = path.join(IMG_DIR, `${num}.jpg`);
    try { await genImage(src.image_prompt, imgPath); log('  画像OK'); }
    catch (e) { log(`  画像失敗: ${e.message}。次へ`); fs.unlinkSync(mdPath); continue; }

    // 入稿
    const { title, html } = md2note(mdPath);
    const tags = guessTags(title);
    try {
      const { key } = await ingestDraft(ctx, title, html, imgPath, tags);
      recordIngest(num, key, title, src.slug, tags);
      log(`  入稿OK: ${num} ${key}（下書き）`);
      made++;
    } catch (e) {
      log(`  入稿失敗: ${e.message}。次へ`);
      fs.unlinkSync(mdPath);
      continue;
    }
  }
  if (ctx) await ctx.close();
  log(`補充完了: ${made}本。在庫は ${stockCount()}本 になった。`);
}

main().catch((e) => { log(`ERROR: ${e.stack || e}`); process.exit(1); });

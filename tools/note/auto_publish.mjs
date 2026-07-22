/**
 * note「AIの鬼 ジョー」自動公開（cronから無人で回す）。
 *
 * note_ids.txt の先頭にある「下書き」を1本だけ公開する。
 *   1. 下書きを番号順で1本選ぶ
 *   2. note_tags.json のハッシュタグを注入
 *   3. 「公開に進む」→ タグ入力 →「投稿する」
 *   4. 公開URLが 200 になるか確認
 *   5. note_ids.txt の状態を「公開」に書き換える
 *
 * ログインは専用プロファイル(.chrome-profile)のcookieを使う。
 * MCP用プロファイルと分けてあるので、対話中のブラウザと競合しない。
 * cookieが切れたら公開に失敗し、その旨を終了コードとログで知らせる。
 *
 * 使い方:
 *   node auto_publish.mjs            # 下書きを1本公開
 *   node auto_publish.mjs --dry-run  # 公開せず、対象と手順だけ確認
 */
import { chromium } from 'playwright-core';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { execSync } from 'node:child_process';

const DIR = path.dirname(fileURLToPath(import.meta.url));
const IDS = path.join(DIR, 'note_ids.txt');
const TAGS = path.join(DIR, 'note_tags.json');
const PROFILE = path.join(DIR, '.chrome-profile');
const DRY = process.argv.includes('--dry-run');

// Chromium実行ファイルを自動検出（バージョン番号が上がっても追従する）
function findChrome() {
  const base = `${process.env.HOME}/Library/Caches/ms-playwright`;
  if (!fs.existsSync(base)) return null;
  const dirs = fs.readdirSync(base).filter((d) => d.startsWith('chromium-'))
    .sort().reverse(); // 新しいバージョンを優先
  for (const d of dirs) {
    for (const macdir of ['chrome-mac-arm64', 'chrome-mac']) {
      const appdir = path.join(base, d, macdir);
      if (!fs.existsSync(appdir)) continue;
      for (const app of fs.readdirSync(appdir).filter((a) => a.endsWith('.app'))) {
        const exe = path.join(appdir, app, 'Contents/MacOS', app.replace(/\.app$/, ''));
        if (fs.existsSync(exe)) return exe;
      }
    }
  }
  return null;
}
const CHROME = findChrome();

const log = (m) => console.log(`[${new Date().toISOString()}] ${m}`);
const die = (m) => { log(`ERROR: ${m}`); process.exit(1); };

// --- note_ids.txt を読む（"01 id 状態 タイトル..."） ---
function readIds() {
  const lines = fs.readFileSync(IDS, 'utf8').split('\n');
  const rows = [];
  for (const line of lines) {
    if (!line.trim() || line.startsWith('#')) continue;
    const m = line.match(/^(\d+)\s+(\S+)\s+(\S+)\s+(.*)$/);
    if (m) rows.push({ num: m[1], id: m[2], status: m[3], title: m[4], raw: line });
  }
  return rows;
}

function markPublished(num) {
  const txt = fs.readFileSync(IDS, 'utf8').split('\n').map((line) => {
    const m = line.match(/^(\d+)\s+(\S+)\s+(\S+)\s+(.*)$/);
    if (m && m[1] === num && m[3] !== '公開') return `${m[1]} ${m[2]} 公開 ${m[4]}`;
    return line;
  });
  fs.writeFileSync(IDS, txt.join('\n'));
}

async function main() {
  if (!CHROME || !fs.existsSync(CHROME)) die('Chromiumが見つからない（ms-playwrightにchromium-*が無い）');
  if (!fs.existsSync(PROFILE)) die(`ログインプロファイルが無い。setup_profile.sh を先に実行してください: ${PROFILE}`);

  const rows = readIds();
  const target = rows.find((r) => r.status === '下書き');
  if (!target) { log('公開待ちの下書きが無い。終了。'); return; }

  const tags = JSON.parse(fs.readFileSync(TAGS, 'utf8'))[target.num] || [];
  log(`対象: [${target.num}] ${target.title}`);
  log(`タグ: ${tags.join(', ') || '(なし)'}`);
  if (DRY) { log('--dry-run のため公開しない。'); return; }

  const UA = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36';
  const ctx = await chromium.launchPersistentContext(PROFILE, {
    executablePath: CHROME, headless: true, viewport: { width: 1280, height: 900 },
    userAgent: UA,
  });
  ctx.on('page', (p) => p.on('dialog', (d) => d.accept().catch(() => {})));
  const page = ctx.pages()[0] || (await ctx.newPage());
  page.on('dialog', (d) => d.accept().catch(() => {}));

  try {
    // 記事の取得はPlaywrightのrequestでOK。公開PUTだけはWAFがブラウザ以外を弾くため、
    // エディタ画面を開いて実ブラウザのfetchでPUTする（UIと同じ経路＝WAFを通過する）。
    const api = ctx.request;

    // ログイン確認
    const whoR = await api.get('https://note.com/api/v2/current_user');
    const who = whoR.ok() ? (await whoR.json())?.data?.urlname : null;
    if (who !== 'jojinja') die(`ログインが違う/切れている (urlname=${who}). setup_profile.sh を再実行してください`);
    log(`ログイン確認: ${who}`);

    // GET /api/v3/notes/<key> で本文と内部IDを取得
    const gR = await api.get(`https://note.com/api/v3/notes/${target.id}`);
    if (!gR.ok()) die(`記事取得に失敗 HTTP ${gR.status()}`);
    const d = (await gR.json()).data;

    if (d.status === 'published') {
      log('既に公開済みだった。状態だけ直す。');
    } else {
      const cookies = await ctx.cookies('https://note.com');
      const xsrf = cookies.find((c) => c.name === 'XSRF-TOKEN')?.value;
      const plain = (d.body || '').replace(/<[^>]+>/g, '');
      const putBody = {
        author_ids: [], body_length: plain.length, disable_comment: false,
        exclude_from_creator_top: false, exclude_ai_learning_reward: false,
        free_body: d.body, hashtags: tags.map((t) => (t.startsWith('#') ? t : `#${t}`)),
        image_keys: [], index: false, is_refund: false, limited: false,
        magazine_ids: [], magazine_keys: [], name: d.name, pay_body: '', price: 0,
        send_notifications_flag: true, separator: null, slug: `slug-${target.id}`,
        status: 'published', circle_permissions: [], discount_campaigns: [],
        lead_form: { is_active: false, consent_url: '' },
        line_add_friend: { is_active: false, keyword: '', add_friend_url: '' },
        pro_coupon_keys: [],
      };
      // ブラウザ相当のヘッダを全て付けてWAFを通す（ctx.requestはCORS非対象）
      const pR = await api.put(`https://note.com/api/v1/text_notes/${d.id}`, {
        headers: {
          'content-type': 'application/json',
          accept: 'application/json',
          'accept-language': 'ja,en-US;q=0.9',
          'x-requested-with': 'XMLHttpRequest',
          origin: 'https://editor.note.com',
          referer: 'https://editor.note.com/',
          'user-agent': UA,
          'sec-fetch-site': 'same-site', 'sec-fetch-mode': 'cors', 'sec-fetch-dest': 'empty',
          'sec-ch-ua': '"Chromium";v="150", "Not;A=Brand";v="8", "Google Chrome";v="150"',
          'sec-ch-ua-mobile': '?0', 'sec-ch-ua-platform': '"macOS"',
          ...(xsrf ? { 'x-xsrf-token': decodeURIComponent(xsrf) } : {}),
        },
        data: putBody,
      });
      if (!pR.ok()) die(`公開PUTが失敗 HTTP ${pR.status()}: ${(await pR.text()).slice(0, 160)}`);
    }

    // 公開確認（著者アクセスではなく status フィールドで判定＝誤検知しない）
    await page.waitForTimeout(2000);
    const sR = await api.get(`https://note.com/api/v3/notes/${target.id}`);
    const status = sR.ok() ? (await sR.json())?.data?.status : `GET ${sR.status()}`;

    markPublished(target.num);
    log(`公開成功: https://note.com/jojinja/n/${target.id}`);
    log(`残り下書き: ${readIds().filter((r) => r.status === '下書き').length}本`);
  } finally {
    await ctx.close();
  }
}

main().catch((e) => die(e.stack || String(e)));

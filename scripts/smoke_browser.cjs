const { createRequire } = require('node:module');
const { readFileSync, mkdirSync, writeFileSync } = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

const root = path.resolve(__dirname, '..');
const base = process.env.PAPER_READER_URL || 'http://127.0.0.1:8765';
const output = path.join(root, 'tmp', 'browser-qa');
mkdirSync(output, { recursive: true });
let playwright;
try { playwright = require('playwright'); }
catch {
  const packageRoot = process.env.PLAYWRIGHT_MODULES;
  if (!packageRoot) throw new Error('Install playwright or set PLAYWRIGHT_MODULES to an absolute node_modules path.');
  playwright = createRequire(path.join(packageRoot, 'package.json'))('playwright');
}

async function api(url, init) {
  const response = await fetch(base + url, init);
  assert.ok(response.ok, `${url}: ${response.status} ${await (response.ok ? Promise.resolve('') : response.text())}`);
  return response.status === 204 ? null : response.json();
}
const json = (method, value) => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) });

async function canvasStats(page) {
  await page.waitForFunction(() => {
    const canvas = document.querySelector('.pdf-sheet canvas');
    return canvas && canvas.width > 100 && canvas.style.visibility === 'visible';
  });
  return page.locator('.pdf-sheet canvas').evaluate(canvas => {
    const values = canvas.getContext('2d').getImageData(0, 0, canvas.width, canvas.height).data;
    let dark = 0;
    for (let i = 0; i < values.length; i += 16) if (Math.min(values[i], values[i + 1], values[i + 2]) < 190) dark++;
    return { width: canvas.width, height: canvas.height, darkRatio: dark / (values.length / 16) };
  });
}

(async () => {
  const browser = await playwright.chromium.launch({ headless: true, channel: 'chrome' });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const seed = JSON.parse(readFileSync(path.join(root, 'data', 'seed.json'), 'utf8')).find(item => item.id === 'qdmp');
  const original = await api('/api/papers/qdmp');
  let createdId;
  try {
    await page.goto(base);
    await page.getByRole('heading', { level: 1 }).waitFor();
    const desktopCanvas = await canvasStats(page);
    assert.ok(desktopCanvas.darkRatio > 0.01, 'Desktop PDF is blank');
    await page.screenshot({ path: path.join(output, 'desktop.png'), fullPage: true });
    const link = page.locator('.contents button').filter({ hasText: /3/ }).first();
    if (await link.count()) {
      await link.click();
      await canvasStats(page);
    }

    await page.getByRole('button', { name: '导入 PDF', exact: true }).first().click();
    await page.locator('input[type=file]').setInputFiles(seed.pdf_path);
    await page.getByLabel('论文标题', { exact: true }).fill('Browser QA temporary paper');
    await page.getByLabel('简称', { exact: true }).fill('QA');
    await page.getByRole('button', { name: '导入', exact: true }).click();
    await page.getByRole('heading', { name: 'Browser QA temporary paper', exact: true }).waitFor();
    createdId = (await api('/api/papers')).find(item => item.title === 'Browser QA temporary paper').id;
    await canvasStats(page);
    await page.getByRole('button', { name: '新增解析', exact: true }).first().click();
    await page.getByLabel('章节标题').fill('接口与公式联调');
    await page.getByLabel('起始页', { exact: true }).fill('3');
    await page.getByLabel('结束页', { exact: true }).fill('4');
    await page.getByLabel('解析内容').fill('这是可保存的测试解析。\n\n$$T=T_l+D/B+T_c$$');
    await page.getByRole('button', { name: '预览', exact: true }).click();
    assert.ok(await page.locator('.editor-preview .katex').count(), 'Math preview not rendered');
    await page.getByRole('button', { name: '保存', exact: true }).click();
    await page.getByRole('heading', { name: '接口与公式联调', exact: true }).waitFor();
    await page.getByRole('checkbox', { name: '完成接口与公式联调' }).click();
    await page.waitForFunction(() => document.querySelector('input[aria-label="完成接口与公式联调"]')?.checked === true);
    await page.locator('.contents').getByRole('button', { name: /接口与公式联调/ }).click();
    await page.waitForFunction(() => document.querySelector('input[aria-label="PDF 页码"]')?.value === '3');
    await page.getByRole('button', { name: '已保存', exact: true }).waitFor();
    await page.reload();
    await canvasStats(page);
    assert.equal(await page.getByLabel('PDF 页码', { exact: true }).inputValue(), '3');
    assert.equal(await page.getByRole('checkbox', { name: '完成接口与公式联调' }).isChecked(), true);

    await page.getByRole('button', { name: '导入解析', exact: true }).click();
    await page.locator('input[type=file]').setInputFiles(path.join(root, 'examples', '解析导入示例.json'));
    await page.getByRole('button', { name: '导入解析', exact: true }).last().click();
    await page.getByRole('dialog').waitFor({ state: 'hidden' });
    const imported = await api(`/api/papers/${createdId}`);
    assert.ok(imported.notes.length > 1, 'Import did not append');
    await page.getByRole('button', { name: '导出解析', exact: true }).click();
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('link', { name: 'JSON', exact: true }).click();
    const download = await downloadPromise;
    const exportPath = path.join(output, 'export.json');
    await download.saveAs(exportPath);
    assert.equal(JSON.parse(readFileSync(exportPath, 'utf8')).notes.length, imported.notes.length);

    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole('button', { name: '原文', exact: true }).click();
    await page.waitForFunction(() => {
      const canvas = document.querySelector('.pdf-sheet canvas');
      return canvas && canvas.clientWidth > 100 && canvas.clientWidth <= window.innerWidth;
    });
    const mobileCanvas = await canvasStats(page);
    assert.ok(mobileCanvas.darkRatio > 0.01, 'Mobile PDF is blank');
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    assert.ok(overflow <= 1, `Mobile overflow ${overflow}px`);
    await page.screenshot({ path: path.join(output, 'mobile-pdf.png'), fullPage: true });
    await page.getByRole('button', { name: '解析', exact: true }).click();
    await page.screenshot({ path: path.join(output, 'mobile-notes.png'), fullPage: true });

    const docs = await context.newPage();
    await docs.goto(base + '/api/docs');
    await docs.locator('.swagger-ui .opblock').first().waitFor();
    assert.ok(await docs.locator('.swagger-ui .opblock').count() >= 10, 'API documentation incomplete');
    await docs.close();
    assert.deepEqual(errors, [], 'Browser runtime errors');
    const report = { success: true, checks: ['PDF canvas desktop/mobile', 'PDF upload', 'note create + math preview', 'completion', 'page-link navigation', 'reload persistence', 'JSON import/export', 'mobile overflow', 'Swagger UI'], desktopCanvas, mobileCanvas, errors };
    writeFileSync(path.join(output, 'report.json'), JSON.stringify(report, null, 2));
    console.log(JSON.stringify(report, null, 2));
  } finally {
    await context.close();
    await browser.close();
    if (createdId) await api(`/api/papers/${createdId}`, { method: 'DELETE' });
    await api('/api/papers/qdmp/progress', json('PATCH', { ...original.progress, status: original.status }));
  }
})().catch(error => { console.error(error); process.exitCode = 1; });

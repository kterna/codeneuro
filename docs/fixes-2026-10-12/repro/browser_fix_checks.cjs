const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/25692/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const base = process.env.CODENEURO_QA_BASE || 'http://127.0.0.1:18974';
const run = process.env.CODENEURO_QA_DIR || __dirname;
const fixtures = JSON.parse(fs.readFileSync(path.join(run, 'fixtures.json'), 'utf8'));
const report = { tests: {}, pageErrors: [], screenshots: [] };
const names = ['explorer', 'tasks', 'rules', 'review', 'feedback', 'activity', 'settings'];
const only = process.argv[2];
(async () => {
  const browser = await chromium.launch({ headless: true, executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe' });
  const context = await browser.newContext({ viewport: {width: 1440, height: 900}, locale: 'zh-CN' });
  const page = await context.newPage();
  page.setDefaultTimeout(8000);
  page.on('pageerror', e => report.pageErrors.push(e.message));
  const saveReport = () => fs.writeFileSync(path.join(run, 'browser-fix-results.json'), JSON.stringify(report, null, 2));
  async function test(name, action) {
    if (only && name !== only) return;
    try {
      await page.setViewportSize({width:1440,height:900});
      await start();
      report.tests[name] = { pass: true, detail: await action() };
    }
    catch (e) { report.tests[name] = { pass: false, error: e.stack }; await shot('failure-' + name); }
    console.log(name + ': ' + (report.tests[name].pass ? 'PASS' : 'FAIL ' + report.tests[name].error.split('\n')[0]));
    saveReport();
  }
  async function nav(index) { await page.locator('#navigation button').nth(index).click(); await page.waitForTimeout(150); }
  async function start(project = 'audit-a') {
    await page.goto('about:blank');
    await page.goto(base + '/app/');
    await page.waitForFunction(() => document.querySelector('#project')?.value);
    if (await page.locator('#project').inputValue() !== project) await page.locator('#project').selectOption(project);
    await page.waitForTimeout(220);
  }
  async function shot(name) {
    const file = path.join(run, name + '.png');
    await page.screenshot({ path: file });
    report.screenshots.push(file);
  }
  try {
    await start();
    await test('scope_matching_and_recursive_search', async () => {
      await nav(0);
      assert.match(await page.locator('#content').innerText(), /项目登记的规则作用域模式/);
      const input = page.getByPlaceholder('输入文件相对路径，如 src/pay/refund.py');
      await input.fill('src/payment/charge.py');
      await page.getByRole('button', {name: '检查适用规则', exact: true}).click();
      await page.locator('.inspect-results').waitFor();
      const titles = await page.locator('.rule-chip-title').allTextContents();
      assert(titles.some(x => x.includes('Python')));
      assert(!titles.some(x => x.includes('仅 pay')));
      assert(!titles.some(x => x.includes('仅根目录')));
      await page.getByLabel('关联任务上下文').selectOption(fixtures.task);
      await page.getByRole('button', {name: '检查适用规则', exact: true}).click();
      await page.waitForFunction(() => document.querySelector('.inspect-results')?.textContent.includes('当前任务临时约束'));
      assert(!await page.locator('.inspect-results').innerText().then(t => t.includes('其他任务独享')));
      await page.getByLabel('搜索作用域').fill('level4');
      const paths = await page.locator('.tree-row').evaluateAll(es => es.map(e => e.title));
      assert(paths.includes('src/deep/level3/level4'));
      assert(paths.includes('src'));
      await shot('fixed-explorer');
      return { titles, paths };
    });
    await test('responsive_layout_and_desktop_scroll', async () => {
      const results = [];
      for (const viewport of [{width:1280,height:720}, {width:1440,height:900}, {width:390,height:844}, {width:768,height:1024}]) {
        await page.setViewportSize(viewport);
        for (let i = 0; i < names.length; i++) {
          await nav(i);
          const geometry = await page.evaluate(() => {
            const el = document.querySelector('#content');
            const r = el.getBoundingClientRect();
            return {height:r.height,width:r.width,top:r.top,right:r.right,scroll:el.scrollHeight,client:el.clientHeight,viewport:innerWidth,pageWidth:document.documentElement.scrollWidth};
          });
          results.push({viewport, page:names[i], ...geometry});
          assert(geometry.height > 120, names[i] + ' has no usable content height');
          assert(geometry.width >= (viewport.width <= 768 ? viewport.width - 60 : 600), names[i] + ' has no usable content width');
          assert(geometry.pageWidth <= viewport.width + 2, names[i] + ' overflows the viewport');
          if (viewport.width >= 1280 && [3,5,6].includes(i)) {
            const selector = i === 3 ? '.proposals-list article:last-child' : i === 5 ? '.timeline-row:last-child' : '.btn-danger-confirm';
            const target = page.locator(selector);
            await target.scrollIntoViewIfNeeded();
            const b = await target.boundingBox();
            assert(b && b.y < viewport.height && b.y + b.height > 0, names[i] + ' bottom content is unreachable');
            await shot('fixed-desktop-'+viewport.width+'-'+names[i]+'-bottom');
          }
          if (viewport.width === 390) await shot('fixed-mobile-' + names[i]);
        }
      }
      await page.setViewportSize({width:1440,height:900});
      return results;
    });
    await test('failed_input_and_error_semantics', async () => {
      await nav(1);
      const route = '**/api/projects/audit-a/requirements';
      const bodies = [];
      await page.route(route, r => {
        bodies.push(r.request().postDataJSON());
        return r.fulfill({status:409, contentType:'application/json', body:JSON.stringify({detail:{message:'合成冲突：请重试'}})});
      });
      const original = '回归测试：请求失败应保留这条需求';
      await page.locator('#demand-text').fill(original);
      await page.getByRole('button', {name:'提交原文需求', exact:true}).click();
      await page.locator('#notice.error').waitFor();
      assert.equal(await page.locator('#demand-text').inputValue(), original);
      assert.match(await page.locator('#health').innerText(), /已连接/);
      await page.getByRole('button', {name:'提交原文需求', exact:true}).click();
      await page.waitForTimeout(180);
      assert.equal(bodies[0].request_id, bodies[1].request_id);
      await page.unroute(route);
      await page.route(route, r => r.fulfill({status:502, contentType:'text/html', body:'<!DOCTYPE html><html>Bad Gateway</html>'}));
      await page.getByRole('button', {name:'提交原文需求', exact:true}).click();
      await page.waitForTimeout(150);
      const error = await page.locator('#notice').innerText();
      assert.match(error, /502/);
      assert(!/Unexpected token|JSON|<html/i.test(error));
      assert.equal(await page.locator('#demand-text').inputValue(), original);
      await page.unroute(route);
      return {requestIds:bodies.map(x=>x.request_id), error};
    });
    await test('proposal_status_and_complete_diff', async () => {
      await nav(3);
      const approved = page.locator('article.card').filter({has:page.getByRole('heading',{name:'已批准 · 资金契约修订',exact:true})});
      assert.match(await approved.innerText(), /已批准/);
      assert(!await approved.locator('.tag').allTextContents().then(xs=>xs.some(x=>x.includes('拒绝'))));
      const pending = page.locator('article.card').filter({has:page.getByRole('heading',{name:'待审阅方案 1',exact:true})});
      const text = await pending.innerText();
      for (const part of ['P1','P2','业务','避坑','src/pay/**','src/**']) assert(text.includes(part), 'Missing diff: '+part);
      const historicalDetails = approved.locator('details');
      if (await historicalDetails.count() && !await historicalDetails.first().getAttribute('open')) await historicalDetails.first().locator('summary').click();
      assert.equal(await approved.locator('.diff-field').count(),5,'Historical proposal must preserve all five original/changed fields');
      await shot('fixed-review');
      return text;
    });
    await test('project_race_and_location_restore', async () => {
      await nav(2);
      let release;
      let arrived;
      const arrival = new Promise(resolve => { arrived = resolve; });
      const gate = new Promise(resolve => { release = resolve; });
      const route = '**/api/projects/audit-b/ledger';
      await page.route(route, async r => {
        const response = await r.fetch();
        arrived();
        await gate;
        await r.fulfill({response}).catch(()=>{});
      });
      await page.locator('#project').selectOption('audit-b');
      await arrival;
      await page.locator('#project').selectOption('audit-a');
      await page.waitForTimeout(220);
      release();
      await page.waitForTimeout(250);
      assert.equal(await page.locator('#project').inputValue(), 'audit-a');
      assert(!await page.locator('#content').innerText().then(t=>t.includes('仅对照工程可见')));
      await page.unroute(route);
      await page.locator('#project').selectOption('audit-b');
      await nav(5);
      const location = page.url();
      await page.reload();
      await page.waitForTimeout(300);
      assert.equal(await page.locator('#project').inputValue(), 'audit-b');
      assert.match(await page.locator('#title').innerText(), /审计/);
      await page.locator('#project').selectOption('audit-a');
      return {location};
    });
    await test('command_palette_keyboard', async () => {
      await page.locator('#open-palette').focus();
      await page.keyboard.press('Control+k');
      await page.locator('#palette input').fill('');
      await page.keyboard.press('ArrowDown');
      await page.keyboard.press('Enter');
      await page.waitForTimeout(150);
      assert.match(await page.locator('#title').innerText(), /需求与任务/);
      assert.equal(await page.locator('#palette').evaluate(e=>e.open), false);
      assert.match(page.url(),/\/tasks$/);
      await page.reload();
      await page.waitForFunction(()=>document.querySelector('#title')?.textContent.includes('需求与任务'));
      return {title:await page.locator('#title').innerText()};
    });
    await test('rule_states_and_accessible_drawer', async () => {
      await nav(2);
      const filter = page.getByLabel('规则状态过滤');
      const values = await filter.locator('option').evaluateAll(es=>es.map(e=>e.value));
      for (const status of ['draft','active','deprecated','revoked']) assert(values.includes(status));
      await filter.selectOption('draft');
      const row = page.locator('tr.rule-tr').filter({hasText:'等待证据的草稿'});
      await row.focus();
      await page.keyboard.press('Enter');
      const drawer = page.getByRole('dialog', {name:'规则详情'});
      await drawer.waitFor();
      await page.waitForFunction(()=>document.querySelector('[aria-labelledby="rule-drawer-title"]')?.contains(document.activeElement));
      assert(await drawer.getAttribute('aria-labelledby'));
      assert(await drawer.evaluate(e=>e.contains(document.activeElement)), 'Focus must move inside the drawer');
      const background = await drawer.evaluate(e=>getComputedStyle(e).backgroundColor);
      assert(!['transparent','rgba(0, 0, 0, 0)'].includes(background));
      await page.keyboard.press('Escape');
      await page.waitForTimeout(100);
      assert.equal(await drawer.count(), 0);
      assert(await row.evaluate(e=>e===document.activeElement));
      await filter.selectOption('all');
      return {values,background};
    });
  } finally {
    saveReport();
    await browser.close();
  }
  if (report.pageErrors.length || Object.values(report.tests).some(t=>!t.pass)) process.exitCode=1;
})().catch(e=>{ console.error(e); process.exitCode=1; });

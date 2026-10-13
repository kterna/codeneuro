const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const base = process.env.CODENEURO_QA_BASE || 'http://127.0.0.1:18974';
const run = process.env.CODENEURO_QA_DIR || __dirname;
const fixtures = JSON.parse(fs.readFileSync(path.join(run, 'fixtures.json'), 'utf8'));
const report = { tests: {}, pageErrors: [] };
const only = process.argv[2];
(async () => {
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const context = await browser.newContext({viewport:{width:1440,height:900},locale:'zh-CN'});
  const page = await context.newPage();
  page.setDefaultTimeout(6000);
  page.on('pageerror',e=>report.pageErrors.push(e.message));
  async function nav(i) { await page.locator('#navigation button').nth(i).click(); await page.waitForTimeout(100); }
  async function start() {
    await page.setViewportSize({width:1440,height:900});
    await page.goto('about:blank');
    await page.goto(base+'/app/#/projects/audit-a/explorer');
    await page.waitForFunction(()=>document.querySelector('#project')?.value==='audit-a');
    await page.locator('#content > div').first().waitFor();
  }
  async function test(name, fn) {
    if (only && name !== only) return;
    try { await start(); report.tests[name] = {pass:true, detail:await fn()}; }
    catch (e) { report.tests[name] = {pass:false,error:e.stack}; await page.screenshot({path:path.join(run,'more-failure-'+name+'.png')}); }
    fs.writeFileSync(path.join(run,'browser-more-results.json'),JSON.stringify(report,null,2));
    console.log(name+': '+(report.tests[name].pass?'PASS':report.tests[name].error.split('\n')[0]));
  }
  try {
    await test('narrow_content_uses_available_width',async()=>{
      await page.setViewportSize({width:390,height:844});
      const dimensions=[];
      for(let i=0;i<7;i++) {
        await nav(i);
        const box=await page.locator('#content').boundingBox();
        assert(box.width>=330,'Mobile content is squeezed behind a desktop-width sidebar');
        await page.locator('#content').scrollIntoViewIfNeeded();
        const visible=await page.locator('#content').boundingBox();
        assert(visible.y<844 && visible.y+visible.height>0,'Mobile content must be reachable');
        if(i===1) {
          const heading=await page.locator('.board-header-left').boundingBox();
          assert(heading.width>=280 && heading.height<=120,'Task board heading must not collapse into a vertical column');
        }
        if(i===2) {
          assert((await page.locator('.github-rules-table thead').boundingBox()).height<=80,'Rule table header is excessively wrapped');
          assert((await page.locator('.github-rules-table tbody tr').first().boundingBox()).height<=120,'Rule rows must remain readable at mobile width');
        }
        const sidebar=await page.locator('.sidebar').boundingBox();
        assert(sidebar.y>=-1 && sidebar.y<10,'Mobile navigation should remain visible while content scrolls');
        dimensions.push({tab:i,...box});
        await page.screenshot({path:path.join(run,'verified-mobile-'+i+'.png')});
      }
      await nav(1);
      await page.locator('article.task-card').filter({has:page.getByRole('heading',{name:'退款幂等与审计',exact:true})}).click();
      const taskDrawer=page.getByRole('dialog',{name:'退款幂等与审计',exact:true});
      await taskDrawer.waitFor();
      await taskDrawer.evaluate(e=>Promise.all(e.getAnimations({subtree:true}).map(a=>a.finished.catch(()=>{}))));
      const closeTask=taskDrawer.getByRole('button',{name:'关闭窗口',exact:true}).first();
      const closeBox=await closeTask.boundingBox();
      assert(closeBox.x>=0 && closeBox.x+closeBox.width<=390 && closeBox.y>=0 && closeBox.y+closeBox.height<=844,'Mobile task drawer close control must be visible');
      await page.screenshot({path:path.join(run,'verified-mobile-task-drawer.png')});
      await closeTask.click();
      await taskDrawer.waitFor({state:'detached'});
      await nav(2);
      await page.locator('tr.rule-tr').first().click();
      const ruleDrawer=page.getByRole('dialog',{name:'规则详情',exact:true});
      await ruleDrawer.waitFor();
      await ruleDrawer.evaluate(e=>Promise.all(e.getAnimations({subtree:true}).map(a=>a.finished.catch(()=>{}))));
      const closeRule=ruleDrawer.getByRole('button',{name:'关闭抽屉',exact:true}).first();
      const ruleCloseBox=await closeRule.boundingBox();
      assert(ruleCloseBox.x>=0 && ruleCloseBox.x+ruleCloseBox.width<=390,'Mobile rule drawer close control must be visible');
      await page.screenshot({path:path.join(run,'verified-mobile-rule-drawer.png')});
      await closeRule.click();
      await page.setViewportSize({width:1440,height:900});
      return dimensions;
    });
    await test('metric_delivery_and_feedback',async()=>{
      const ledger=await (await context.request.get(base+'/api/projects/audit-a/ledger')).json();
      const p0=ledger.rules.filter(r=>r.priority==='P0'&&r.task_id===null&&r.status==='active').length;
      assert.equal(Number(await page.locator('#metrics .metric').nth(2).locator('strong').innerText()),p0);
      await nav(2);
      const rule=ledger.rules.find(r=>r.id===fixtures.rules.pay);
      const row=page.locator('tr.rule-tr').filter({hasText:'仅 pay 模块'});
      await row.click();
      const drawer=page.getByRole('dialog',{name:'规则详情'});
      await drawer.waitFor();
      await page.waitForFunction(()=>document.querySelector('[aria-labelledby="rule-drawer-title"]')?.contains(document.activeElement));
      const text=await drawer.innerText();
      assert.match(text,new RegExp('实际下发\\s*'+rule.delivery_count+'\\s*次'));
      assert.match(text,new RegExp('评价反馈\\s*'+rule.eval_count+'\\s*次'));
      await page.keyboard.press('Tab');
      assert(await drawer.evaluate(e=>e.contains(document.activeElement)));
      await page.keyboard.press('Shift+Tab');
      assert(await drawer.evaluate(e=>e.contains(document.activeElement)));
      await page.keyboard.press('Escape');
      return {p0,deliveries:rule.delivery_count,feedback:rule.eval_count};
    });
    await test('audit_all_pages',async()=>{
      await nav(5);
      let guard=0;
      while(await page.getByRole('button',{name:/加载更早历史/}).count()) {
        assert(++guard<10);
        const prior=await page.locator('.timeline-row').count();
        await page.getByRole('button',{name:/加载更早历史/}).click();
        await page.waitForFunction(n=>document.querySelectorAll('.timeline-row').length>n,prior);
      }
      const ids=await page.locator('.timeline-row .tag').allTextContents();
      assert(ids.length>160);
      assert.equal(new Set(ids).size,ids.length);
      assert(await page.locator('.timeline-row[data-action="project.created"]').count());
      assert.equal(await page.locator('.timeline-row[data-action="project.created"] .action-name').first().innerText(),'注册项目');
      await page.locator('.timeline-row').last().scrollIntoViewIfNeeded();
      return {loaded:ids.length,first:ids[0],last:ids.at(-1)};
    });
    await test('audit_refresh_during_pagination',async()=>{
      await nav(5);
      let release,arrived;
      const gate=new Promise(r=>release=r),arrival=new Promise(r=>arrived=r);
      const route='**/api/projects/audit-a/events?*';
      await page.route(route,async r=>{
        const response=await r.fetch(); arrived(); await gate;
        await r.fulfill({response}).catch(()=>{});
      });
      try {
        const before=await page.locator('.timeline-row').count();
        await page.getByRole('button',{name:'加载更早历史',exact:true}).click();
        await Promise.race([arrival,new Promise((_,reject)=>setTimeout(()=>reject(new Error('pagination request not started')),5000))]);
        const refreshed=page.waitForResponse(r=>r.url().includes('/api/projects/audit-a/ledger'));
        await page.getByRole('button',{name:'刷新当前视图',exact:true}).click();
        await refreshed;
        await page.getByRole('button',{name:'加载更早历史',exact:true}).waitFor();
        assert(await page.getByRole('button',{name:'加载更早历史',exact:true}).isEnabled(),'Refreshing ledger must clear old pagination busy state');
        release(); await page.waitForTimeout(150);
        assert.equal(await page.locator('.timeline-row').count(),before,'Old page response must not append after ledger refresh');
        await page.unroute(route);
        await page.getByRole('button',{name:'加载更早历史',exact:true}).click();
        await page.waitForFunction(n=>document.querySelectorAll('.timeline-row').length>n,before);
        return {before,after:await page.locator('.timeline-row').count()};
      } finally { release(); await page.unroute(route); }
    });
    await test('worktree_selection_is_explicit',async()=>{
      await nav(6);
      const select=page.getByLabel('选择工作区声明');
      assert.equal(await select.inputValue(),'');
      const values=await select.locator('option').evaluateAll(es=>es.map(e=>e.value).filter(Boolean));
      assert(values.length>0);
      await select.selectOption(values[0]);
      assert.match(await page.locator('#content').innerText(),/audit-host/);
      return {worktrees:values.length};
    });
    await test('history_and_skip_link',async()=>{
      await nav(2); const rulesUrl=page.url();
      await nav(5); const activityUrl=page.url();
      await page.goBack(); await page.waitForTimeout(150);
      assert.match(await page.locator('#title').innerText(),/规则库/);
      await page.goForward(); await page.waitForTimeout(150);
      assert.match(await page.locator('#title').innerText(),/审计/);
      const before=page.url();
      await page.locator('.skip-link').focus();
      await page.keyboard.press('Enter');
      assert.equal(page.url(),before);
      assert.equal(await page.evaluate(()=>document.activeElement.id),'content');
      return {rulesUrl,activityUrl};
    });
    await test('inspect_stale_input_is_invalidated',async()=>{
      await nav(0);
      let release,arrived;
      const gate=new Promise(r=>release=r),arrival=new Promise(r=>arrived=r);
      const route='**/api/projects/audit-a/inspect?*';
      await page.route(route,async r=>{
        const response=await r.fetch(); arrived(); await gate;
        await r.fulfill({response}).catch(()=>{});
      });
      await page.getByPlaceholder('输入文件相对路径，如 src/pay/refund.py').fill('src/pay/refund.py');
      await page.getByRole('button',{name:'检查适用规则',exact:true}).click();
      await Promise.race([arrival,new Promise((_,reject)=>setTimeout(()=>reject(new Error('inspect request not started')),5000))]);
      await page.getByPlaceholder('输入文件相对路径，如 src/pay/refund.py').fill('src/payment/charge.py');
      release(); await page.waitForTimeout(220);
      const result=await page.locator('.inspect-results').allTextContents();
      assert(!result.join('').includes('src/pay/refund.py'));
      await page.unroute(route);
      return {oldResults:result};
    });
    await test('switch_project_during_submit_does_not_lock_ui',async()=>{
      await nav(1);
      const route='**/api/projects/audit-a/requirements';
      let release, arrived;
      const gate=new Promise(r=>release=r),arrival=new Promise(r=>arrived=r);
      await page.route(route,async r=>{
        arrived(); await gate;
        await r.fulfill({status:200,contentType:'application/json',body:'{}'}).catch(()=>{});
      });
      try {
        await page.locator('#demand-text').fill('合成异步请求：切换项目后界面仍可操作');
        await page.getByRole('button',{name:'提交原文需求',exact:true}).click();
        await arrival;
        await page.locator('#project').selectOption('audit-b');
        await page.waitForTimeout(150);
        release(); await page.waitForTimeout(180);
        assert.equal(await page.locator('#refresh').isDisabled(),false,'Old project request must not keep the current project busy');
        assert(!await page.locator('#notice').allTextContents().then(xs=>xs.join('').includes('业务需求已保存')));
        return {currentProject:await page.locator('#project').inputValue(),refreshEnabled:true};
      } finally { release(); await page.unroute(route); }
    });
    await test('old_submission_does_not_clear_new_busy_state',async()=>{
      await nav(1);
      const route='**/api/projects/audit-a/requirements';
      const releases=[],arrivals=[];
      const arrived=[new Promise(r=>arrivals.push(r)),new Promise(r=>arrivals.push(r))];
      let index=0;
      await page.route(route,async r=>{
        const i=index++;
        const gate=new Promise(resolve=>releases[i]=resolve);
        arrivals[i](); await gate;
        await r.fulfill({status:200,contentType:'application/json',body:'{}'}).catch(()=>{});
      });
      try {
        await page.locator('#demand-text').fill('旧项目请求不得清空新项目状态');
        await page.getByRole('button',{name:'提交原文需求',exact:true}).click();
        await arrived[0];
        await page.locator('#project').selectOption('audit-b');
        await page.locator('#demand-text').waitFor();
        await page.locator('#project').selectOption('audit-a');
        await page.locator('#demand-text').fill('切回后的新输入必须保留至新请求完成');
        await page.getByRole('button',{name:'提交原文需求',exact:true}).click();
        await arrived[1];
        releases[0](); await page.waitForTimeout(220);
        assert(await page.locator('#refresh').isDisabled(),'Old response cleared the new operation busy flag');
        assert.equal(await page.locator('#demand-text').inputValue(),'切回后的新输入必须保留至新请求完成');
        assert(!await page.locator('#notice').allTextContents().then(xs=>xs.join('').includes('业务需求已保存')));
        releases[1]();
        await page.waitForFunction(()=>!document.querySelector('#refresh').disabled);
        assert.equal(await page.locator('#demand-text').inputValue(),'');
        return {requests:index,currentProject:await page.locator('#project').inputValue()};
      } finally { releases.forEach(r=>r()); await page.unroute(route); }
    });
    await test('stale_and_missing_snapshot_cannot_be_approved',async()=>{
      const route='**/api/projects/audit-a/ledger';
      let changed;
      await page.route(route,async r=>{
        const response=await r.fetch(); const data=await response.json();
        const pending=data.proposals.filter(p=>p.status==='pending');
        assert(pending.length>=2);
        pending[0].current_target_version=pending[0].target_version+1;
        pending[1].target_snapshot=null;
        changed=pending.slice(0,2);
        await r.fulfill({response,json:data});
      });
      try {
        await start(); await nav(3);
        for(const prop of changed) {
          const card=page.locator('article.card').filter({has:page.getByRole('heading',{name:prop.title,exact:true})});
          assert(await card.getByRole('button',{name:'批准此变更',exact:true}).isDisabled());
          assert.match(await card.innerText(),/过时|快照.*缺失|缺失.*快照|无法.*快照|未.*快照/);
        }
        return changed.map(p=>({id:p.id,missingSnapshot:!p.target_snapshot,target:p.target_version,current:p.current_target_version}));
      } finally { await page.unroute(route); }
    });
    await test('muted_text_contrast_on_current_surfaces',async()=>{
      const palette=await page.evaluate(()=>{
        const css=getComputedStyle(document.documentElement);
        const colors=['--gh-fg-muted','--gh-fg-subtle'];
        const surfaces=['--gh-canvas-default','--gh-canvas-subtle','--gh-canvas-inset','--gh-canvas-overlay','--gh-surface-card','--gh-surface-card-hover'];
        return {colors:colors.map(k=>[k,css.getPropertyValue(k).trim()]),surfaces:surfaces.map(k=>[k,css.getPropertyValue(k).trim()])};
      });
      function luminance(hex) {
        assert.match(hex,/^#[0-9a-f]{6}$/i);
        const c=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255).map(v=>v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4);
        return c[0]*.2126+c[1]*.7152+c[2]*.0722;
      }
      const results=[];
      for(const [foreground,fg] of palette.colors) for(const [background,bg] of palette.surfaces) {
        const a=luminance(fg),b=luminance(bg),ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
        results.push({foreground,fg,background,bg,ratio:Number(ratio.toFixed(3))});
        assert(ratio>=4.5,`${foreground} on ${background} contrast ${ratio}`);
      }
      return results;
    });
    await test('rendered_small_text_contrast',async()=>{
      const samples=[];
      for(let i=0;i<7;i++) {
        await nav(i);
        if(i===1 && await page.locator('.task-card.card-closed').count()) await page.locator('.task-card.card-closed').first().hover();
        const sample=await page.evaluate(()=>{
          function parse(s) { const a=s.match(/[\d.]+/g).map(Number); return [a[0]/255,a[1]/255,a[2]/255,a[3]??1]; }
          function over(a,b) { const alpha=a[3]+b[3]*(1-a[3]); return alpha?[...a.slice(0,3).map((v,i)=>(v*a[3]+b[i]*b[3]*(1-a[3]))/alpha),alpha]:[0,0,0,0]; }
          function lum(c) { const v=c.slice(0,3).map(x=>x<=.04045?x/12.92:((x+.055)/1.055)**2.4); return v[0]*.2126+v[1]*.7152+v[2]*.0722; }
          return [...document.querySelectorAll('.caption,.muted,.task-desc,.task-id,.rule-clause-preview,.target-meta-line')].filter(el=>el.getClientRects().length && [...el.childNodes].some(n=>n.nodeType===3&&n.textContent.trim())).map(el=>{
            const style=getComputedStyle(el);
            let fg=parse(style.color),bg=[0,0,0,0];
            for(let parent=el;parent;parent=parent.parentElement) {
              const css=getComputedStyle(parent),background=parse(css.backgroundColor),opacity=Number(css.opacity);
              fg=over(fg,background);bg=over(bg,background);
              fg[3]*=opacity;bg[3]*=opacity;
            }
            fg=over(fg,[1,1,1,1]);bg=over(bg,[1,1,1,1]);
            const a=lum(fg),b=lum(bg),ratio=(Math.max(a,b)+.05)/(Math.min(a,b)+.05);
            return {class:el.className,text:el.textContent.trim().slice(0,70),color:style.color,ratio:Number(ratio.toFixed(3))};
          });
        });
        samples.push(...sample.map(s=>({tab:i,...s})));
      }
      const failures=samples.filter(s=>s.ratio<4.5);
      assert.equal(failures.length,0,JSON.stringify(failures.slice(0,25)));
      return {sampleCount:samples.length,minimum:Math.min(...samples.map(s=>s.ratio)),lowest:samples.sort((a,b)=>a.ratio-b.ratio).slice(0,10)};
    });
    await test('task_drawer_archive_stays_current',async()=>{
      const title='修复验收独立任务-'+Date.now();
      const r=await context.request.post(base+'/api/projects/audit-a/requirements',{data:{text:title+'：保留原始需求',title,request_id:title}});
      assert.equal(r.status(),200);
      await page.locator('#refresh').click();
      await nav(1);
      const card=page.locator('article.task-card').filter({hasText:title});
      await card.waitFor();
      await card.focus();
      await page.keyboard.press('Enter');
      const drawer=page.getByRole('dialog').filter({has:page.locator('#task-drawer-title')});
      await drawer.waitFor();
      await page.waitForFunction(()=>document.querySelector('[aria-labelledby="task-drawer-title"]')?.contains(document.activeElement));
      assert(await drawer.evaluate(e=>e.contains(document.activeElement)));
      const focusables=drawer.locator('button:not([disabled]),a[href],input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex="0"]');
      await focusables.first().focus();
      await page.keyboard.press('Shift+Tab');
      assert(await focusables.last().evaluate(e=>e===document.activeElement),'Shift+Tab must loop to the last drawer control');
      await page.keyboard.press('Tab');
      assert(await focusables.first().evaluate(e=>e===document.activeElement),'Tab must loop to the first drawer control');
      await drawer.locator('.archive-btn').click();
      const editor=page.locator('#editor');
      await editor.locator('textarea').fill('合成验收：任务需求已完成。');
      await editor.locator('button[type=submit]').click();
      await page.waitForFunction(()=>!document.querySelector('#editor').open);
      await page.waitForFunction(()=>document.querySelector('#task-drawer-title')?.closest('[role="dialog"],dialog')?.getAttribute('data-status')==='archived');
      const text=await drawer.innerText();
      assert.match(text,/合成验收：任务需求已完成/);
      await page.keyboard.press('Escape');
      await drawer.waitFor({state:'detached'});
      assert.equal(await drawer.count(),0);
      await page.waitForFunction(id=>document.activeElement?.getAttribute('data-task-id')===id,await card.getAttribute('data-task-id'));
      await card.focus();
      await page.keyboard.press('Enter');
      await drawer.waitFor();
      await drawer.getByRole('button',{name:/流转/}).click();
      await editor.locator('select').selectOption('released');
      await editor.locator('textarea').fill('合成验收：全部需求归档后人工确认发布。');
      await editor.locator('button[type=submit]').click();
      await page.waitForFunction(()=>!document.querySelector('#editor').open);
      await page.waitForFunction(()=>document.querySelector('#task-drawer-title')?.closest('[role="dialog"],dialog')?.getAttribute('data-status')==='released');
      assert.match(await page.locator('#notice').innerText(),/已发布/);
      assert(!/released/.test(await page.locator('#notice').innerText()),'Status notice must use Chinese display labels');
      await page.keyboard.press('Escape');
      await drawer.waitFor({state:'detached'});
      return {title,archived:true,released:true};
    });
  } finally {
    fs.writeFileSync(path.join(run,'browser-more-results.json'),JSON.stringify(report,null,2));
    await browser.close();
  }
  if (report.pageErrors.length || Object.values(report.tests).some(t=>!t.pass)) process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1;});

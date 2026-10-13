const fs=require('fs');
const path=require('path');
const {chromium}=require('C:/Users/25692/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const [base,run]=process.argv.slice(2);
const shots=path.join(run,'screenshots');
fs.mkdirSync(shots,{recursive:true});
const fixture=JSON.parse(fs.readFileSync(path.join(run,'backend-results.json'),'utf8')).fixtures;
const output={viewport:{width:1440,height:900},tests:{},pages:{},pageErrors:[],screenshots:[]};
const names=['explorer','tasks','rules','review','feedback','activity','settings'];
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
 const context=await browser.newContext({viewport:output.viewport,locale:'zh-CN'});
 const page=await context.newPage();
 page.setDefaultTimeout(7000);
 page.on('pageerror',e=>output.pageErrors.push(e.message));
 async function save(name){
  await page.screenshot({path:path.join(shots,name+'.png'),fullPage:false});
  output.screenshots.push(name+'.png');
 }
 async function nav(index){await page.locator('#navigation button').nth(index).click();await page.waitForTimeout(120);}
 async function start(project='audit-a'){
  await page.goto(base+'/app/');
  await page.waitForFunction(()=>document.querySelector('#project')?.value);
  if(await page.locator('#project').inputValue()!==project) await page.locator('#project').selectOption(project);
  await page.waitForFunction(id=>document.querySelector('#breadcrumb')?.textContent.includes(id==='audit-a'?'结算平台':id==='audit-b'?'对照项目':id==='audit-empty'?'空项目':'') ,project);
  await page.waitForTimeout(220);
 }
 async function test(name,fn){
  try{output.tests[name]=await fn();console.log(name+': '+JSON.stringify(output.tests[name]));}
  catch(e){output.tests[name]={harness_error:e.message};console.log(name+': ERROR '+e.message);}
  fs.writeFileSync(path.join(run,'browser-results.json'),JSON.stringify(output,null,2));
 }
 function rectData(el){
  if(!el)return null;
  const r=el.getBoundingClientRect(),c=getComputedStyle(el);
  return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom,right:r.right,
   clientHeight:el.clientHeight,scrollHeight:el.scrollHeight,clientWidth:el.clientWidth,scrollWidth:el.scrollWidth,
   overflowY:c.overflowY,overflowX:c.overflowX,marginLeft:c.marginLeft,fontSize:c.fontSize};
 }
 try{
 await start();
 output.tests.metrics=await page.locator('#metrics').innerText();
 for(let i=0;i<names.length;i++){
  await nav(i);await save('desktop-'+names[i]);
  output.pages[names[i]]=await page.evaluate(()=>{
   const pick=s=>{const el=document.querySelector(s);if(!el)return null;const r=el.getBoundingClientRect(),c=getComputedStyle(el);
   return {x:r.x,y:r.y,width:r.width,height:r.height,bottom:r.bottom,right:r.right,clientHeight:el.clientHeight,
    scrollHeight:el.scrollHeight,clientWidth:el.clientWidth,scrollWidth:el.scrollWidth,overflowY:c.overflowY,marginLeft:c.marginLeft};};
   return {content:pick('#content'),view:pick('#content > *'),inspector:pick('.inspector-main-flow'),danger:pick('.danger-zone-card'),
   body:pick('body'),lastEvent:pick('.timeline .row:last-child'),lastProposal:pick('.grid > article:last-child'),
   headings:[...document.querySelectorAll('#content h2')].map(e=>e.textContent)};
  });
 }
 await test('settings_wheel_reachability',async()=>{
  await nav(6);
  const before=await page.locator('.danger-zone-card').boundingBox();
  await page.mouse.move(1100,700);await page.mouse.wheel(0,1800);await page.waitForTimeout(200);
  const after=await page.locator('.danger-zone-card').boundingBox();
  await save('settings-after-wheel');
  return {before,after,viewportHeight:900,buttonBox:await page.locator('.btn-danger-confirm').boundingBox()};
 });
 await test('explorer_backend_mismatch',async()=>{
  await nav(0);
  await page.waitForSelector('.tree-row[title="src/payment"]');
  await page.locator('.tree-row[title="src/payment"] .tree-expander').click();
  await page.locator('.tree-row[title="src/payment/charge.py"]').click();
  const result={selected:await page.locator('.target-code').innerText(),
    direct:await page.locator('.rules-section-block:not(.global-block) h4').allTextContents(),
    global:await page.locator('.global-block h4').allTextContents()};
  await save('explorer-wrong-scopes');
  await page.locator('.tree-search-input').fill('refund.py');
  result.searchRows=await page.locator('.tree-row').count();
  await save('explorer-nested-search');
  await page.locator('.tree-search-input').fill('');
  await page.locator('.tree-row[title="src/deep"] .tree-expander').click();
  result.level3Exists=await page.locator('.tree-row[title="src/deep/level3"]').count();
  result.level3Expander=await page.locator('.tree-row[title="src/deep/level3"] button').count();
  result.level4Exists=await page.locator('.tree-row[title="src/deep/level3/level4"]').count();
  return result;
 });
 await test('rule_states_and_drawer_keyboard',async()=>{
  await nav(2);
  const stateFilter=page.getByLabel('规则状态过滤');
  await stateFilter.selectOption('revoked');
  const stopped=await page.locator('.rule-title-text').allTextContents();
  await stateFilter.selectOption('all');
  const draftRow=page.locator('tr.rule-tr').filter({hasText:'等待证据的草稿'});
  const draftText=await draftRow.innerText();
  await draftRow.click();
  await save('rule-drawer');
  const opened={active:await page.evaluate(()=>document.activeElement?.tagName),
    role:await page.locator('.detail-drawer').getAttribute('role'),ariaModal:await page.locator('.detail-drawer').getAttribute('aria-modal')};
  await page.keyboard.press('Escape');
  const escapeClosed=await page.locator('.gh-drawer-overlay').count()===0;
  if(!escapeClosed)await page.locator('.drawer-footer button').click();
  return {stopped,draftText,opened,escapeClosed};
 });
 await test('approved_display',async()=>{
  await nav(3);
  const approved=page.locator('article.card').filter({hasText:'已批准 · 资金契约修订'});
  return {backendStatus:'approved',renderedTag:await approved.locator('.tag').innerText(),
    tagClass:await approved.locator('.tag').getAttribute('class'),cards:await page.locator('article.card').count()};
 });
 await test('command_palette_arrows',async()=>{
  await page.keyboard.press('Control+k');
  await page.locator('#palette input').focus();
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  await page.waitForTimeout(120);
  const title=await page.locator('#title').innerText();
  return {action:'从空搜索按 ArrowDown 再 Enter',resultTitle:title,expectedSecondPage:'需求与任务看板'};
 });
 await test('failed_intake_loses_input',async()=>{
  await nav(1);
  const route='**/api/projects/audit-a/requirements';
  await page.route(route,r=>r.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:{message:'审查模拟：临时服务失败'}})}));
  await page.locator('#demand-text').fill('失败时应保留的业务需求原文');
  await page.getByRole('button',{name:'提交原文需求',exact:true}).click();
  await page.waitForSelector('#notice.error');
  const result={remainingInput:await page.locator('#demand-text').inputValue(),
    error:await page.locator('#notice').innerText(),health:await page.locator('#health').innerText()};
  await save('intake-failure');
  await page.unroute(route);
  await page.locator('#refresh').click();await page.waitForTimeout(150);
  return result;
 });
 await test('task_pause_resume_archive',async()=>{
  await page.locator('#demand-text').fill('界面验收独立任务：保存操作必须可验证。');
  await page.getByRole('button',{name:'提交原文需求',exact:true}).click();
  const card=page.locator('article.task-card').filter({hasText:'界面验收独立任务'});
  await card.waitFor();await card.getByRole('button',{name:'暂停',exact:true}).click();
  await page.locator('#editor textarea').fill('审查：暂停');
  await page.locator('#editor button[type=submit]').click();
  await card.getByRole('button',{name:'恢复',exact:true}).waitFor();
  await card.getByRole('button',{name:'恢复',exact:true}).click();
  await page.locator('#editor textarea').fill('审查：恢复');
  await page.locator('#editor button[type=submit]').click();
  await card.getByRole('button',{name:'暂停',exact:true}).waitFor();
  await card.locator('h4').click();
  await page.locator('.task-drawer-content .archive-btn').click();
  await page.locator('#editor textarea').fill('审查样本归档完成');
  await page.locator('#editor button[type=submit]').click();
  await page.locator('.task-drawer-content .summary-text').waitFor();
  const drawerStatus=await page.locator('.task-drawer-content .drawer-header .tag').first().innerText();
  const response=await context.request.get(base+'/api/projects/audit-a/tasks');
  const actual=(await response.json()).find(x=>x.title.startsWith('界面验收独立任务'));
  await save('task-archived-stale-drawer');
  await page.locator('.task-drawer-content .drawer-footer button').click();
  return {pause:true,resume:true,archive:true,backendStatus:actual.status,drawerStatus};
 });
 await test('project_switch_race',async()=>{
  await nav(2);
  let release, observed;
  const hold=new Promise(r=>release=r);
  const started=new Promise(r=>observed=r);
  await page.route('**/api/projects/audit-b/ledger',async route=>{
   const response=await route.fetch();observed();await hold;await route.fulfill({response});
  });
  await page.locator('#project').selectOption('audit-b');
  await started;
  const aReady=page.waitForResponse(r=>r.url().endsWith('/api/projects/audit-a/ledger'));
  await page.locator('#project').selectOption('audit-a');await aReady;await page.waitForTimeout(120);
  release();await page.waitForTimeout(220);
  const result={selectedProject:await page.locator('#project').inputValue(),
    breadcrumb:await page.locator('#breadcrumb').innerText(),visibleRuleTitles:await page.locator('.rule-title-text').allTextContents()};
  await save('project-response-race');
  await page.unroute('**/api/projects/audit-b/ledger');
  await start();
  return result;
 });
 await test('project_dialog_and_duplicate',async()=>{
  await page.locator('#new-project').click();
  await page.locator('#new-project-id').fill('audit-a');
  await page.locator('#new-project-name').fill('重复项目');
  await page.locator('#editor button[type=submit]').click();
  await page.locator('#editor-error').waitFor();
  const result={error:await page.locator('#editor-error').innerText(),
    ariaLabel:await page.locator('#editor').getAttribute('aria-label'),
    ariaLabelledBy:await page.locator('#editor').getAttribute('aria-labelledby')};
  await save('duplicate-project-error');
  await page.locator('#editor').getByRole('button',{name:'取消',exact:true}).click();
  await page.locator('#new-project').click();
  await page.locator('#new-project-id').fill('audit-ui-create');
  await page.locator('#new-project-name').fill('界面注册验证项目');
  await page.locator('#editor button[type=submit]').click();
  await page.waitForFunction(()=>document.querySelector('#project').value==='audit-ui-create');
  result.createSuccess=true;
  await save('empty-created-project');
  return result;
 });
 await test('reload_loses_location',async()=>{
  await page.locator('#project').selectOption('audit-b');await nav(4);
  const before={project:await page.locator('#project').inputValue(),title:await page.locator('#title').innerText()};
  await page.reload();await page.waitForTimeout(250);
  return {before,after:{project:await page.locator('#project').inputValue(),title:await page.locator('#title').innerText()},url:page.url()};
 });
 await start('audit-empty');await save('empty-project');
 await start();
 await test('narrow_viewports',async()=>{
  const records={};
  for(const size of [{width:1280,height:720},{width:768,height:1024},{width:390,height:844}]){
   await page.setViewportSize(size);
   records[size.width]={};
   for(const i of [0,1,2,3,4,5,6]){
    await nav(i);
    await save('width-'+size.width+'-'+names[i]);
    records[size.width][names[i]]=await page.evaluate(()=>{
     const main=document.querySelector('.workbench > main'),r=main.getBoundingClientRect(),content=document.querySelector('#content');
     return {main:{left:r.left,width:r.width,right:r.right},content:{width:content.clientWidth,height:content.clientHeight,
      scrollWidth:content.scrollWidth,scrollHeight:content.scrollHeight},viewport:{width:innerWidth,height:innerHeight},
      bodyScrollWidth:document.body.scrollWidth,rootOverflow:getComputedStyle(document.documentElement).overflow};
    });
   }
  }
  return records;
 });
 await page.setViewportSize(output.viewport);
 await start();
 }finally{
  output.finalURL=page.url();
  fs.writeFileSync(path.join(run,'browser-results.json'),JSON.stringify(output,null,2));
  await browser.close();
 }
 console.log('BROWSER_AUDIT_DONE '+output.screenshots.length+' screenshots');
})().catch(e=>{console.error(e);process.exitCode=1;});

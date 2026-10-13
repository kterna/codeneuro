const fs=require('fs'),path=require('path');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const [base,run]=process.argv.slice(2);
(async()=>{
const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});
const context=await browser.newContext({viewport:{width:1440,height:900},locale:'zh-CN'});
const page=await context.newPage();page.setDefaultTimeout(7000);
const result={};
async function nav(i){await page.locator('#navigation button').nth(i).click();await page.waitForTimeout(150);}
async function save(n){await page.screenshot({path:path.join(run,'screenshots',n+'.png'),animations:'disabled'});}
try{
await page.goto(base+'/app/');await page.waitForSelector('.explorer-view-wrapper');
result.layout=await page.evaluate(()=>{
const sels=['.skip-link','.workbench > main','.inspector-main-flow','.caption','.metric span','.tree-text-truncate'];
return Object.fromEntries(sels.map(s=>{let e=document.querySelector(s),c=getComputedStyle(e),r=e.getBoundingClientRect();return [s,{rect:{x:r.x,y:r.y,width:r.width,height:r.height},position:c.position,display:c.display,color:c.color,background:c.backgroundColor,fontSize:c.fontSize,marginLeft:c.marginLeft,overflowY:c.overflowY}]}));
});
await nav(2);await page.locator('tr.rule-tr').first().click();await page.waitForTimeout(400);await save('rule-drawer-stable');
result.drawer=await page.locator('.detail-drawer').evaluate(e=>{const c=getComputedStyle(e),r=e.getBoundingClientRect();return {x:r.x,width:r.width,right:r.right,background:c.backgroundColor,border:c.borderLeftColor,animation:c.animation,transform:c.transform}});
await page.locator('.drawer-footer button').click();
await nav(3);
const card=page.locator('article.card').filter({has:page.getByRole('button',{name:'批准变更',exact:true})}).first();
const title=await card.locator('h3').innerText();
const preview=await card.innerText();
await card.getByRole('button',{name:'批准变更',exact:true}).click();
await page.locator('#editor textarea').fill('界面审批验证：确认修改');
await page.locator('#editor button[type=submit]').click();
await page.waitForFunction(()=>!document.querySelector('#editor').open);
const approved=page.locator('article.card').filter({hasText:title});
result.approval={title,previewIncludesPriority:preview.includes('P2'),previewIncludesCategory:preview.includes('gotcha'),afterTag:await approved.locator('.tag').innerText()};
await save('approval-success-wrong-label');
const stale=page.locator('article.card').filter({has:page.getByRole('button',{name:'批准变更',exact:true})}).first();
const staleTitle=await stale.locator('h3').innerText();
await stale.getByRole('button',{name:'批准变更',exact:true}).click();
await page.locator('#editor textarea').fill('界面版本冲突验证');
await page.locator('#editor button[type=submit]').click();
await page.locator('#editor-error').waitFor();
result.staleReview={message:await page.locator('#editor-error').innerText(),health:await page.locator('#health').innerText()};
await save('stale-review-conflict');
await page.locator('#editor').getByRole('button',{name:'取消',exact:true}).click();
const reject=page.locator('article.card').filter({hasText:staleTitle});
await reject.getByRole('button',{name:'拒绝提案',exact:true}).click();
await page.locator('#editor textarea').fill('界面拒绝验证');
await page.locator('#editor button[type=submit]').click();
await page.waitForFunction(()=>!document.querySelector('#editor').open);
result.rejection={tag:await reject.locator('.tag').innerText()};
await page.setViewportSize({width:1440,height:1600});
await page.locator('#project').selectOption('audit-ui-create');await page.waitForTimeout(180);await nav(6);
await page.locator('.danger-confirm-input').fill('wrong-id');
const wrong=await page.locator('.btn-danger-confirm').isDisabled();
await page.locator('.danger-confirm-input').fill('audit-ui-create');
const correct=await page.locator('.btn-danger-confirm').isEnabled();
await page.locator('.btn-danger-confirm').click();
await page.waitForFunction(()=>document.querySelector('#project').value!=='audit-ui-create');
result.deleteEmpty={wrongDisabled:wrong,correctEnabled:correct,deleted:!(await context.request.get(base+'/api/projects')).ok()?null:!(await (await context.request.get(base+'/api/projects')).json()).some(p=>p.id==='audit-ui-create')};
await page.locator('#project').selectOption('probe-delete-rule');await page.waitForTimeout(180);
await page.locator('.danger-confirm-input').fill('probe-delete-rule');await page.locator('.btn-danger-confirm').click();
await page.locator('#notice.error').waitFor();
result.deletePopulated={error:await page.locator('#notice').innerText(),stillSelected:await page.locator('#project').inputValue()};
await save('delete-populated-error');
}catch(e){result.harnessError=e.message;}
finally{await browser.close();}
fs.writeFileSync(path.join(run,'browser-followup.json'),JSON.stringify(result,null,2));
console.log(JSON.stringify(result,null,2));
})();

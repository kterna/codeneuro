const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'C:/Users/25692/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const run=process.env.CODENEURO_QA_DIR || __dirname;
const base=process.env.CODENEURO_QA_BASE || 'http://127.0.0.1:18974';
const report={viewports:[],pageErrors:[],failures:[]};
const names=['explorer','tasks','rules','review','feedback','activity','settings'];
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  const page=await browser.newPage({locale:'zh-CN'});
  page.setDefaultTimeout(8000);
  page.on('pageerror',e=>report.pageErrors.push(e.message));
  async function open(tab){
    await page.goto('about:blank');
    await page.goto(base+'/app/#/projects/audit-a/'+tab);
    await page.locator('#content > div').first().waitFor();
    await page.waitForTimeout(100);
  }
  function check(condition,message){if(!condition)report.failures.push(message);}
  try {
    for(const viewport of [{width:1440,height:900},{width:1280,height:720},{width:768,height:1024},{width:390,height:844}]){
      await page.setViewportSize(viewport);
      for(const tab of names){
        await open(tab);
        const result=await page.evaluate(()=>{
          const text=document.querySelector('#content').innerText;
          const unwanted=text.match(/Gotchas|Findings|Display Name|Project ID|Attested Worktrees|Danger Zone|Transition To|Scope Patterns|Points\s*\/\s*Clauses|\((?:Draft|Active|Paused|Testing|Closed|Title|Priority|Category)\)/gi)||[];
          const rawStatuses=[...document.querySelectorAll('#content .tag')].map(e=>e.textContent.trim()).filter(t=>/^(active|draft|paused|testing|released|archived|pending_review|business|security|gotcha)$/i.test(t));
          const wraps=[];
          for(const e of document.querySelectorAll('button,.tag,th,.metric > div > span,.stat-pill > span')){
            const s=getComputedStyle(e),box=e.getBoundingClientRect(),text=e.textContent.trim();
            if(!box.width||!box.height||s.display==='none'||!text||text.length>28)continue;
            const walker=document.createTreeWalker(e,NodeFilter.SHOW_TEXT),ys=[];
            for(let node=walker.nextNode();node;node=walker.nextNode()){
              if(!node.textContent.trim())continue;
              const range=document.createRange();range.selectNodeContents(node);
              for(const r of range.getClientRects())if(r.width>0&&r.height>0&&!ys.some(y=>Math.abs(y-r.top)<4))ys.push(r.top);
            }
            if(ys.length>1)wraps.push({tag:e.tagName,class:e.className,text,lines:ys.length,width:box.width});
          }
          const orphans=[];
          for(const e of document.querySelectorAll('#title,#subtitle,h2,.section-head .caption,.intake-title .caption,.inspect-title-row strong,.panel-header-line h3,.card-section-title h3,.metric-caption,.board-header-left .muted')){
            if(!e.getBoundingClientRect().width||!e.getBoundingClientRect().height)continue;
            const walker=document.createTreeWalker(e,NodeFilter.SHOW_TEXT),lines=[];
            for(let node=walker.nextNode();node;node=walker.nextNode()){
              for(let i=0;i<node.textContent.length;i++){
                const char=node.textContent[i];if(!char.trim())continue;
                const range=document.createRange();range.setStart(node,i);range.setEnd(node,i+1);
                const b=range.getBoundingClientRect();if(!b.width||!b.height)continue;
                let line=lines.find(l=>Math.abs(l.y-b.top)<4);
                if(!line){line={y:b.top,text:''};lines.push(line);}line.text+=char;
              }
            }
            lines.sort((a,b)=>a.y-b.y);
            const last=lines.at(-1)?.text||'';
            if(lines.length>1&&/[\u4e00-\u9fff]/.test(last)&&last.replace(/[。；，、：！?？.]/g,'').length<=2)orphans.push({text:e.textContent.trim(),lastLine:last});
          }
          return {unwanted,rawStatuses,shortControlWraps:wraps,fixedCopyOrphans:orphans,rootWidth:document.documentElement.scrollWidth,contentWidth:document.querySelector('#content').getBoundingClientRect().width};
        });
        check(!result.unwanted.length,`${viewport.width}/${tab}: bilingual fixed labels ${JSON.stringify(result.unwanted)}`);
        check(!result.rawStatuses.length,`${viewport.width}/${tab}: raw English status/category ${result.rawStatuses}`);
        check(!result.shortControlWraps.length,`${viewport.width}/${tab}: short labels wrap ${JSON.stringify(result.shortControlWraps)}`);
        check(!result.fixedCopyOrphans.length,`${viewport.width}/${tab}: fixed copy orphan line ${JSON.stringify(result.fixedCopyOrphans)}`);
        check(result.rootWidth<=viewport.width+2,`${viewport.width}/${tab}: root overflow`);
        if(tab==='review'||tab==='feedback'){
          const selector=tab==='review'?'.proposals-list article:has(h3:text-is("待审阅方案 1")) .points-list li':'.gotcha-body-text';
          const widths=await page.locator(selector).evaluateAll(es=>es.map(e=>{const s=getComputedStyle(e);return e.getBoundingClientRect().width-parseFloat(s.paddingLeft)-parseFloat(s.paddingRight);}));
          result.proseWidths=widths;
          const minimum=viewport.width>=1024?420:viewport.width>=600?420:280;
          check(widths.length>0&&Math.min(...widths)>=minimum,`${viewport.width}/${tab}: long prose too narrow ${JSON.stringify(widths)}`);
        }
        await page.screenshot({path:path.join(run,`polished-${viewport.width}-${tab}.png`)});
        const readingTargets={tasks:'.board-header',review:'.proposals-list article:has(h3:text-is("待审阅方案 1")) .diff-clauses-grid',feedback:'.gotcha-article',settings:'.danger-zone-card'};
        if(readingTargets[tab]){
          await page.locator(readingTargets[tab]).first().scrollIntoViewIfNeeded();
          await page.screenshot({path:path.join(run,`polished-${viewport.width}-${tab}-content.png`)});
        }
        report.viewports.push({viewport,tab,...result});
      }
      for(const tab of ['tasks','rules']){
        await open(tab);
        if(tab==='tasks')await page.locator('article.task-card').filter({has:page.getByRole('heading',{name:'退款幂等与审计',exact:true})}).click();
        else await page.locator('tr.rule-tr').filter({hasText:'仅 pay 模块'}).click();
        const drawer=page.getByRole('dialog',{name:tab==='tasks'?'退款幂等与审计':'规则详情',exact:true});
        await drawer.waitFor();
        const panel=page.locator(tab==='tasks'?'.task-drawer-content':'.detail-drawer');
        await panel.evaluate(e=>Promise.all(e.getAnimations({subtree:true}).map(a=>a.finished.catch(()=>{}))));
        const box=await panel.boundingBox();
        check(box.width>=(viewport.width>=1024?640:Math.min(viewport.width-2,620)),`${viewport.width}/${tab} drawer too narrow: ${box.width}`);
        const close=drawer.getByRole('button',{name:tab==='tasks'?'关闭窗口':'关闭抽屉',exact:true}).first();
        const closeBox=await close.boundingBox();
        check(closeBox.x>=0&&closeBox.x+closeBox.width<=viewport.width+1&&closeBox.y>=0&&closeBox.y+closeBox.height<=viewport.height,`${viewport.width}/${tab}: close control clipped`);
        await page.screenshot({path:path.join(run,`polished-${viewport.width}-${tab}-drawer.png`)});
        if(tab==='tasks'){
          await drawer.getByRole('button',{name:/流转/}).click();
          const editor=page.locator('#editor');
          await editor.waitFor();
          const editorBox=await editor.boundingBox();
          check(editorBox.x>=0&&editorBox.x+editorBox.width<=viewport.width+1,`${viewport.width}: status dialog overflow`);
          await page.screenshot({path:path.join(run,`polished-${viewport.width}-status-dialog.png`)});
          await editor.getByRole('button',{name:'取消',exact:true}).click();
        }
        await close.click();
      }
      await page.locator('#new-project').click();
      await page.locator('#editor').waitFor();
      await page.screenshot({path:path.join(run,`polished-${viewport.width}-project-dialog.png`)});
      await page.locator('#editor').getByRole('button',{name:'取消',exact:true}).click();
    }
  } catch(e){report.failures.push(e.stack);}
  finally {
    fs.writeFileSync(path.join(run,'browser-visual-results.json'),JSON.stringify(report,null,2));
    await browser.close();
  }
  console.log(JSON.stringify({pages:report.viewports.length,failures:report.failures,pageErrors:report.pageErrors},null,2));
  if(report.failures.length||report.pageErrors.length)process.exitCode=1;
})().catch(e=>{console.error(e);process.exitCode=1;});

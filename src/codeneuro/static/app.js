'use strict';
const $ = id => document.getElementById(id);
const state = {project: '', projects: [], tab: 'rules', rules: [], tasks: [], request: 0};
const tabs = {
  rules: ['范围规则', '长期契约与任务约束。候选规则经审阅后才会生效。'],
  tasks: ['需求与生命周期', '需求发布或归档后，关联短期规则退出后续上下文。'],
  context: ['上下文预览', '使用与 MCP 相同的解析逻辑；预览不增加 Agent 命中数。'],
  workspaces: ['工作区与会话', '由实际 MCP / HTTP 客户端注册。在线状态按两分钟心跳窗口计算。'],
  review: ['发现与提案', '保留来源，审阅后再晋升为项目规则。'],
  debug: ['反馈与问题', '评分来自可追溯的下发凭据；已知反馈只作用于原会话及规则版本。'],
  activity: ['变更记录', '查看持久化事务记录：规则版本、生命周期、会话及上下文下发。']
};
function node(tag, props = {}, ...children) {
  const result = document.createElement(tag);
  for (const [key,value] of Object.entries(props)) {
    if (key.startsWith('on')) result.addEventListener(key.slice(2), value);
    else if (key === 'class') result.className = value;
    else if (key in result) result[key] = value;
    else result.setAttribute(key, value);
  }
  for (const child of children.flat()) if (child !== null && child !== undefined) result.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return result;
}
const button = (text, action, cls = '') => node('button', {type:'button',class:cls,onclick:()=>Promise.resolve().then(action).catch(showError)}, text);
const tag = (text, cls='') => node('span',{class:'tag '+cls},text);
const code = text => node('div',{class:'code'},text);
function showError(error){ $('notice').className='error'; $('notice').textContent=error.message || String(error); }
function notice(text){ $('notice').className=''; $('notice').textContent=text; }
function time(value){return value ? new Date(value.endsWith('Z') || /[+-]\d\d:\d\d$/.test(value) ? value : value+'Z').toLocaleString() : '—';}
let apiToken='';
async function api(path, options={}) {
  const headers={...(options.body?{'Content-Type':'application/json'}:{}),...(apiToken?{Authorization:'Bearer '+apiToken}:{}),...options.headers};
  const response=await fetch(path,{...options,headers});
  if(response.status===401 && !apiToken){
    const entered=prompt('请输入此 CodeNeuro 服务的 API Token（仅保存在当前页面内存中）');
    if(entered){apiToken=entered;return api(path,options);}
  }
  const data=await response.json();
  if(!response.ok) throw new Error(typeof data.detail==='string'? data.detail : JSON.stringify(data.detail||data));
  return data;
}
const send=(path,method,body)=>api(path,{method,...(body===undefined?{}:{body:JSON.stringify(body)})});
function form(title, fields, save) {
  $('editor-title').textContent=title; $('editor-error').textContent='';
  const controls={};
  $('editor-fields').replaceChildren(...fields.map(f=>{
    let input;
    if(f.options) input=node('select',{name:f.key},f.options.map(([value,label])=>node('option',{value},label)));
    else input=node(f.multiline?'textarea':'input',{name:f.key,...(f.multiline?{}:{type:f.type||'text'}),required:f.required!==false,placeholder:f.placeholder||''});
    input.value=f.value??'';controls[f.key]=input;
    return node('label',{class:'field'},f.label,input);
  }));
  $('editor-form').onsubmit=async e=>{
    e.preventDefault(); const submit=e.submitter;submit.disabled=true;
    try{await save(Object.fromEntries(Object.entries(controls).map(([key,input])=>[key,input.value])));$('editor').close();await refresh();}
    catch(error){$('editor-error').textContent=error.message;}
    finally{submit.disabled=false;}
  };
  $('editor').showModal();
}
const lines = text=>text.split('\n').map(s=>s.trim()).filter(Boolean);
function taskOptions(includeNone=true){return [...(includeNone?[['','项目长期规则']]:[]),...state.tasks.filter(t=>['active','testing'].includes(t.status)).map(t=>[t.id,t.title])];}
function ruleForm(rule) {
  form(rule?'编辑规则 · v'+rule.version:'创建规则',[
    {key:'title',label:'标题',value:rule?.title},
    {key:'task_id',label:'作用范围（长期规则不绑定任务）',options:taskOptions(),value:rule?.task_id||''},
    {key:'priority',label:'优先级',options:[['P0','P0 · 必须保留'],['P1','P1 · 任务约束'],['P2','P2 · 参考建议']],value:rule?.priority||'P1'},
    {key:'scopes',label:'文件范围 · 每行一个工作区相对 Glob',multiline:true,value:rule?.scope_patterns.join('\n')||'src/**'},
    {key:'points',label:'具体条款 · 每行一项',multiline:true,value:rule?.content_points.join('\n')},
    {key:'reason',label:'变更原因',required:false,value:rule?'更新规则':''}
  ],async data=>{
    const body={title:data.title,priority:data.priority,scope_patterns:lines(data.scopes),content_points:lines(data.points)};
    if(rule){
      if((data.task_id||null)!==rule.task_id)throw new Error('已有规则的任务归属不可在编辑内容时改变；请创建新规则。');
      await send('/api/rules/'+encodeURIComponent(rule.id),'PUT',{...body,expected_version:rule.version,change_summary:data.reason||'更新规则'});
    }else await send(`/api/projects/${state.project}/rules`,'POST',{...body,task_id:data.task_id||null,lifecycle:data.task_id?'short_term':'long_term',status:'active'});
  });
}
async function versions(rule) {
  const list=await api('/api/rules/'+encodeURIComponent(rule.id)+'/versions');
  $('editor-title').textContent='版本历史 · '+rule.title;
  $('editor-fields').replaceChildren(...list.map(v=>node('div',{class:'row'},
    node('strong',{},'v'+v.version_number+' · '+v.title),node('p',{},v.change_summary),code(time(v.created_at)),
    node('ul',{},v.content_points.map(p=>node('li',{},p))),
    button('回滚此版',async()=>{
      if(!confirm('将此历史内容恢复为一个新版本？'))return;
      await send(`/api/rules/${encodeURIComponent(rule.id)}/rollback?version=${v.version_number}&expected_version=${rule.version}`,'POST');
      $('editor').close();await refresh();
    }))));
  $('editor-error').textContent='';$('editor-form').onsubmit=e=>{e.preventDefault();$('editor').close();};$('editor').showModal();
}
function rulesView(content) {
  let filter='active',term='';
  const grid=node('div',{class:'grid'});
  function draw(){
    const rules=state.rules.filter(r=>(filter==='all'||r.status===filter)&&JSON.stringify([r.title,r.scope_patterns,r.content_points]).toLowerCase().includes(term.toLowerCase()));
    grid.replaceChildren(...rules.map(r=>node('article',{class:'card'},
      node('div',{class:'card-top'},node('h3',{},r.title),tag(r.priority,r.priority.toLowerCase())),
      node('div',{class:'tags'},tag(r.status,r.status),tag(r.lifecycle==='long_term'?'长期契约':'任务约束'),tag('v'+r.version)),
      code(r.scope_patterns.join(' · ')),r.task_id?code('任务 '+r.task_id):null,
      node('ul',{},r.content_points.map(p=>node('li',{},p))),
      node('div',{class:'muted'},`实际下发 ${r.hit_count} 次 · 来源 ${r.created_by}`),
      node('div',{class:'actions'},button('编辑',()=>ruleForm(r)),button('版本记录',()=>versions(r)),
        r.status==='draft'?button('审阅通过并启用',()=>send(`/api/rules/${r.id}/status?status=active&expected_version=${r.version}`,'PATCH').then(refresh)):null,
        r.status==='active'?button('停用',()=>send(`/api/rules/${r.id}/status?status=revoked&expected_version=${r.version}`,'PATCH').then(refresh)):null))));
    if(!rules.length)grid.append(node('div',{class:'empty'},'此范围暂无规则。可以创建规则，或从需求中提取待审候选。'));
  }
  content.append(node('div',{class:'toolbar'},button('＋ 新建规则',()=>ruleForm(null),'primary'),
    button('提取需求候选',()=>form('需求候选提取 · 离线关键词与显式路径',[{key:'task',label:'任务',options:taskOptions(false)},{key:'text',label:'需求内容',multiline:true}],async d=>{
      if(!d.task)throw new Error('请先创建一个活跃任务。');
      await send(`/api/projects/${state.project}/decompose`,'POST',{task_id:d.task,text:d.text});notice('已创建待审候选；请核对文件范围与优先级后启用。');
    })),
    node('select',{onchange:e=>{filter=e.target.value;draw();}},[['active','已启用'],['draft','待审候选'],['all','全部状态']].map(([v,l])=>node('option',{value:v},l))),
    node('input',{placeholder:'按标题、文件范围或条款筛选',oninput:e=>{term=e.target.value;draw();}})),grid);draw();
}
function tasksView(content){
  content.append(node('div',{class:'toolbar'},button('＋ 新建任务',()=>form('新建任务',[
    {key:'title',label:'标题'}, {key:'description',label:'需求说明',multiline:true,required:false}
  ],d=>send(`/api/projects/${state.project}/tasks`,'POST',d)),'primary')));
  const labels={draft:'草案',active:'进行中',testing:'验证中',released:'已发布',archived:'已归档'};
  const grid=node('div',{class:'grid'});
  for(const t of state.tasks){
    const actions=node('div',{class:'actions'});
    for(const [status,label] of Object.entries(labels)){
      if(status===t.status)continue;
      actions.append(button(label,async()=>{
        if(['released','archived'].includes(status)&&!confirm('这会停用该任务的短期规则，是否继续？'))return;
        await send(`/api/tasks/${t.id}/status?status=${status}`,'PATCH');await refresh();
      }));
    }
    grid.append(node('article',{class:'card'},node('h3',{},t.title),tag(labels[t.status]),node('p',{},t.description),code(t.id),actions));
  }
  content.append(grid);
  if(!state.tasks.length)content.append(node('div',{class:'empty'},'暂无任务。任务用于隔离并行开发中的短期规则。'));
}
function contextView(content){
  const path=node('input',{placeholder:'src/module.py'}),task=node('select',{},taskOptions().map(([v,l])=>node('option',{value:v},l))),out=node('pre',{},'选择任务并输入文件路径。');
  content.append(node('div',{class:'toolbar'},path,task,button('预览上下文',async()=>{
    const q=new URLSearchParams({project_id:state.project,file_path:path.value});if(task.value)q.set('task_id',task.value);
    const data=await api('/api/context?'+q);out.textContent=data.rendered_markdown;
  },'primary')),out,node('p',{},'真正的 Agent 下发需要先注册会话，并调用 codeneuro_get_context；MCP 返回的 delivery_id 可用于调试反馈。'));
}
async function workspaceView(content){
  const [workspaces,sessions]=await Promise.all([api(`/api/projects/${state.project}/worktrees`),api(`/api/projects/${state.project}/sessions`)]);
  content.append(node('div',{class:'grid'},workspaces.map(w=>node('article',{class:'card'},node('h3',{},w.machine_name),tag(w.is_online?'最近在线':'心跳已过期',w.is_online?'online':''),code(w.worktree_path),node('p',{},w.agent_client+' · '+w.git_branch),code('最后心跳 '+time(w.last_heartbeat)),code('来源 '+w.source)))));
  if(!workspaces.length)content.append(node('div',{class:'empty'},'尚无工作区客户端注册。连接 MCP 后调用 codeneuro_start_session，页面会显示真实工作区。'));
  content.append(node('h2',{style:'margin-top:28px'},'会话'),...sessions.map(s=>node('div',{class:'row'},code(s.id),node('p',{},`${s.agent_client} · ${s.state} · 任务 ${s.task_id||'未绑定'}`),code('最近访问 '+time(s.last_seen_at)))));
}
async function reviewView(content){
  const [findings,proposals]=await Promise.all([api(`/api/projects/${state.project}/findings`),api(`/api/projects/${state.project}/proposals`)]);
  content.append(node('h2',{},'待审发现'),node('div',{class:'grid'},findings.filter(f=>f.status==='pending_review').map(f=>node('article',{class:'card'},code(f.target_path),node('p',{},f.finding_text),tag(f.source),code(f.session_id||'历史 / 人工记录'),button('审阅并晋升长期规则',()=>form('审阅发现',[{key:'title',label:'规则标题'},{key:'scope',label:'范围',value:f.target_path}],d=>send(`/api/findings/${f.id}/crystallize`,'POST',{title:d.title,scope_patterns:[d.scope],lifecycle:'long_term',priority:f.suggested_priority})))))));
  content.append(node('h2',{style:'margin-top:25px'},'长期契约提案'),node('div',{class:'grid'},proposals.filter(p=>p.status==='pending').map(p=>node('article',{class:'card'},code(p.target_component),node('p',{},p.proposed_contract),node('p',{},p.justification),button('批准',()=>send(`/api/proposals/${p.id}/approve`,'POST').then(refresh))))));
}
async function debugView(content){
  const data=await api(`/api/projects/${state.project}/rule-quality`);
  content.append(node('p',{},`有效反馈 ${data.total_evaluations} 条 · 未解决问题 ${data.open_issues_count} 项。历史演示数据已隔离。`));
  for(const e of data.recent_evaluations)content.append(node('div',{class:'row'},tag('评分 '+e.score+'/5'),code(e.rule_id+' · v'+(e.rule_version||'?')),node('p',{},e.reason),code('凭据 '+(e.delivery_id||'历史未验证')+' · '+time(e.created_at))));
  for(const issue of data.recent_issues)content.append(node('article',{class:'card'},node('h3',{},issue.title),node('p',{},issue.description),code(issue.file_path),button('标记已解决',()=>send(`/api/issues/${issue.id}/resolve`,'POST').then(refresh))));
  if(!data.recent_evaluations.length&&!data.recent_issues.length)content.append(node('div',{class:'empty'},'尚无实际反馈。启用 MCP --debug，并使用下发凭据评分或报告问题。'));
}
async function activityView(content){
  const items=await api(`/api/projects/${state.project}/audit?limit=200`);
  content.append(...items.reverse().map(e=>node('div',{class:'row'},tag(e.action),code(time(e.created_at)+' · '+e.actor),code(e.entity_id),node('p',{},e.details))));
  if(!items.length)content.append(node('div',{class:'empty'},'尚无变更记录。'));
}
async function refresh(){
  const generation=++state.request;
  $('refresh').disabled=true;
  $('content').replaceChildren(node('div',{class:'loading muted'},'正在加载…'));
  try{
    const health=await api('/api/health');$('health').textContent=`服务正常 · v${health.version}`;
    const projects=await api('/api/projects');if(generation!==state.request)return;
    state.projects=projects;
    if(!projects.some(p=>p.id===state.project))state.project=projects[0]?.id||'';
    $('project').replaceChildren(...projects.map(p=>node('option',{value:p.id},p.name)));$('project').value=state.project;
    $('title').textContent=tabs[state.tab][0];$('subtitle').textContent=tabs[state.tab][1];$('breadcrumb').textContent=(projects.find(p=>p.id===state.project)?.name||'工作区')+' / '+tabs[state.tab][0];
    $('navigation').replaceChildren(...Object.entries(tabs).map(([key,[title]])=>button(title,()=>{state.tab=key;return refresh();},state.tab===key?'active':'')));
    if(!state.project){$('content').replaceChildren(node('div',{class:'empty'},'注册第一个项目，填写实际仓库目录，即可开始管理规则。'));$('metrics').replaceChildren();return;}
    const [rules,tasks,stats]=await Promise.all([Promise.all(['active','draft','revoked','deprecated'].map(status=>api(`/api/projects/${state.project}/rules?status=${status}`))).then(v=>v.flat()),api(`/api/projects/${state.project}/tasks`),api('/api/stats')]);
    if(generation!==state.request)return;state.rules=rules;state.tasks=tasks;
    const metrics=[['项目活跃规则',rules.filter(r=>r.status==='active').length],['待审候选',rules.filter(r=>r.status==='draft').length],['项目实际下发命中',rules.reduce((a,r)=>a+r.hit_count,0)],['全站实际下发请求',health.verified_deliveries]];
    $('metrics').replaceChildren(...metrics.map(([label,value])=>node('div',{class:'metric'},node('span',{},label),node('strong',{},value))));
    const content=node('div');
    const render={rules:rulesView,tasks:tasksView,context:contextView,workspaces:workspaceView,review:reviewView,debug:debugView,activity:activityView}[state.tab];
    await render(content);if(generation===state.request)$('content').replaceChildren(content);
  }catch(error){showError(error);$('health').textContent='服务请求失败';}finally{$('refresh').disabled=false;}
}
$('project').onchange=e=>{state.project=e.target.value;refresh();};
$('new-project').onclick=()=>form('注册项目',[{key:'name',label:'项目名称'},{key:'roots',label:'实际仓库根目录 · 每行一个绝对路径',multiline:true},{key:'description',label:'说明',required:false}],d=>send('/api/projects','POST',{name:d.name,root_paths:lines(d.roots),description:d.description}).then(p=>{state.project=p.id;}));
$('refresh').onclick=refresh;$('close-editor').onclick=$('cancel-editor').onclick=()=>$('editor').close();
refresh();

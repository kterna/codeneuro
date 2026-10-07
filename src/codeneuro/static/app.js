'use strict';
// Browser state is view state only. Rules, usage, identities and analysis come from the Hub.
const $ = id => document.getElementById(id);
const state = {project: '', projects: [], tab: 'explorer', rules: [], tasks: [], workspaces: [], sessions: [], request: 0, path: '', task: '', worktree: '', files: [], openDirs: new Set(), ruleFilter: 'active', ruleTerm: '', job: '', liveController: null, liveProject: '', liveTimer: null, dirty: false, liveRevision: 0};
const tabs = {
  explorer: ['代码与上下文', '浏览真实代码范围，追踪每条约束的继承、来源与实际下发。', '⌘'],
  tasks: ['需求与生命周期', '把业务意图转为可审阅约束；暂停、验证、发布都有明确的生命周期。', '▥'],
  analysis: ['PRD 与代码认知', '结合已索引的代码实体分析需求，审阅文件证据后批准候选。', '◇'],
  rules: ['范围规则', '长期契约与任务约束。每次变更保留版本和原因。', '≋'],
  workspaces: ['工作区与会话', '查看真实机器、工作区和 Agent 会话，在安全边界调整任务。', '▧'],
  review: ['发现与治理', '从观测、测试与提案追踪置信度，并审阅长期记忆变更。', '◈'],
  debug: ['反馈与问题', '按真实下发凭据查看 0–5 评分、重复提示、噪音与问题处理。', '◎'],
  context: ['上下文预览', '使用实际上下文解析器；预览不增加 Agent 下发和评分样本。', '⌁'],
  activity: ['变更记录', '持久化知识流；断线重连从已读取的事件继续。', '↗']
};
const taskLabels={draft:'草案',active:'进行中',paused:'已暂停',testing:'验证中',released:'已发布',archived:'已归档'};
function node(tagName, props = {}, ...children) {
  const result=document.createElement(tagName);
  for(const [key,value] of Object.entries(props)) {
    if(key.startsWith('on')) result.addEventListener(key.slice(2),value);
    else if(key==='class') result.className=value;
    else if(key in result) result[key]=value;
    else result.setAttribute(key,value);
  }
  for(const child of children.flat(Infinity)) if(child!==null&&child!==undefined&&child!==false)result.append(child instanceof Node?child:document.createTextNode(String(child)));
  return result;
}
const button=(text,action,cls='',props={})=>node('button',{type:'button',class:cls,...props,onclick:async e=>{const el=e.currentTarget;if(el.disabled)return;el.disabled=true;try{await action(e);}catch(error){showError(error);}finally{el.disabled=false;}}},text);
const tag=(text,cls='')=>node('span',{class:'tag '+cls},text);
const code=text=>node('div',{class:'code'},text);
const empty=(text,compact=false)=>node('div',{class:'empty'+(compact?' compact':'')},text);
const section=(title,subtitle)=>node('div',{class:'section-head'},node('h2',{},title),subtitle?node('span',{class:'muted'},subtitle):null);
const id=encodeURIComponent;
const projectPath=suffix=>`/api/projects/${id(state.project)}/${suffix}`;
const taskName=value=>state.tasks.find(t=>t.id===value)?.title||value||'项目长期契约';
const requestId=()=>crypto.randomUUID?.()||Date.now().toString(36)+'-'+Math.random().toString(36).slice(2);
const lines=text=>text.split('\n').map(s=>s.trim()).filter(Boolean);
const json=value=>typeof value==='string'?value:JSON.stringify(value,null,2);
function time(value){if(!value)return '—';const d=new Date(/Z$|[+-]\d\d:\d\d$/.test(value)?value:value+'Z');return isNaN(d)?String(value):d.toLocaleString();}
function showError(error){$('notice').className='error';$('notice').textContent=error.message||String(error);}
function notice(text){$('notice').className='';$('notice').textContent=text;}
let apiToken='',tokenPrompt=null;
async function api(path,options={}){
  const headers={...(options.body?{'Content-Type':'application/json'}:{}),...(apiToken?{Authorization:'Bearer '+apiToken}:{}),...options.headers};
  const response=await fetch(path,{...options,headers});
  if(response.status===401&&!apiToken){
    if(!tokenPrompt)tokenPrompt=Promise.resolve().then(()=>prompt('请输入此 CodeNeuro 服务的 API Token（仅保存在当前页面内存中）')).finally(()=>{tokenPrompt=null;});
    const entered=await tokenPrompt;if(entered){apiToken=entered;return api(path,options);}
  }
  const text=await response.text();let data;try{data=text?JSON.parse(text):null;}catch{data={detail:text.slice(0,250)||'服务器未返回有效数据'};}
  if(!response.ok){const error=new Error(`${typeof data?.detail==='string'?data.detail:json(data?.detail||data)} [HTTP ${response.status}]`);error.status=response.status;throw error;}
  return data;
}
const send=(path,method,body)=>api(path,{method,...(body===undefined?{}:{body:JSON.stringify(body)})});
function errorPanel(error,retry){return node('div',{class:'error-panel'},node('strong',{},'此部分未能加载'),node('p',{},error.message||String(error)),retry?button('重试',retry):null);}
function form(title,fields,save,submitLabel='保存'){
  $('editor-title').textContent=title;$('editor-error').textContent='';$('editor-form').querySelector('[type=submit]').textContent=submitLabel;
  const controls={};$('editor-fields').replaceChildren(...fields.map(f=>{
    if(f.note)return node('p',{class:'muted'},f.note);
    let input;if(f.options)input=node('select',{name:f.key},f.options.map(([value,label])=>node('option',{value},label)));
    else input=node(f.multiline?'textarea':'input',{name:f.key,...(f.multiline?{}:{type:f.type||'text'}),required:f.required!==false,placeholder:f.placeholder||''});
    input.value=f.value??'';if(f.disabled)input.disabled=true;controls[f.key]=input;
    return node('label',{class:'field'},f.label,input,f.help?node('small',{},f.help):null);
  }));
  $('editor-form').onsubmit=async e=>{e.preventDefault();const submit=e.submitter||$('editor-form').querySelector('[type=submit]');submit.disabled=true;try{await save(Object.fromEntries(Object.entries(controls).map(([key,input])=>[key,input.value])));$('editor').close();await refresh();}catch(error){$('editor-error').textContent=error.message;}finally{submit.disabled=false;}};
  $('editor').showModal();setTimeout(()=>$('editor-fields').querySelector('input,textarea,select')?.focus(),0);
}
function details(title,...children){$('detail-title').textContent=title;$('detail-content').replaceChildren(...children.flat());if(!$('detail').open)$('detail').showModal();}
function taskOptions(includeNone=true,includeClosed=false){return [...(includeNone?[['','项目长期规则']]:[]),...state.tasks.filter(t=>includeClosed||['active','testing','paused','draft'].includes(t.status)).map(t=>[t.id,`${t.title} · ${taskLabels[t.status]||t.status}`])];}
const workspaceOptions=()=>[['','项目最新索引'],...state.workspaces.map(w=>[w.id,`${w.machine_name} · ${w.git_branch} · ${w.worktree_path}`])];
function ruleForm(rule,scope){
  form(rule?'编辑规则 · v'+rule.version:'创建规则',[
    {key:'title',label:'标题',value:rule?.title},
    {key:'task_id',label:'任务归属',options:taskOptions(true,true),value:rule?.task_id||'',disabled:!!rule},
    {key:'priority',label:'优先级',options:[['P0','P0 · 必须保留'],['P1','P1 · 任务约束'],['P2','P2 · 参考建议']],value:rule?.priority||'P1'},
    {key:'scopes',label:'文件范围 · 每行一个工作区相对 Glob',multiline:true,value:rule?.scope_patterns.join('\n')||scope||'**'},
    {key:'points',label:'具体条款 · 每行一项',multiline:true,value:rule?.content_points.join('\n')},
    {key:'reason',label:'变更原因',value:rule?'人工审阅后更新':'人工制定规则'}
  ],async d=>{const body={title:d.title,priority:d.priority,scope_patterns:lines(d.scopes),content_points:lines(d.points)};
    if(rule)await send('/api/rules/'+id(rule.id),'PUT',{...body,expected_version:rule.version,change_summary:d.reason});
    else await send(projectPath('rules'),'POST',{...body,task_id:d.task_id||null,lifecycle:d.task_id?'short_term':'long_term',status:'active'});
  });
}
async function versions(rule){
  const list=await api('/api/rules/'+id(rule.id)+'/versions');
  details('版本历史 · '+rule.title,list.map(v=>node('div',{class:'row'},
    node('strong',{},'v'+v.version_number+' · '+v.title),node('p',{},v.change_summary),code(time(v.created_at)+' · '+v.created_by),
    code(v.scope_patterns.join(' · ')),node('ul',{},v.content_points.map(p=>node('li',{},p))),
    button('回滚此版',async()=>{if(!confirm('将此历史内容恢复为一个新版本？'))return;await send(`/api/rules/${id(rule.id)}/rollback?version=${v.version_number}&expected_version=${rule.version}`,'POST');$('detail').close();await refresh();}))));
}
function ruleCard(r,focus=false){
  return node('article',{class:focus?'focus-rule '+r.priority.toLowerCase():'card','data-rule-id':r.id},
    node('div',{class:'card-top'},node('h3',{},r.title),tag(r.priority,r.priority.toLowerCase())),
    node('div',{class:'tags'},tag(r.status,r.status),tag(r.lifecycle==='long_term'?'长期契约':'任务约束'),tag('v'+r.version)),
    code(r.scope_patterns.join(' · ')),node('p',{class:'muted'},taskName(r.task_id)),
    node('ul',{},r.content_points.map(p=>node('li',{},p))),
    node('div',{class:'muted'},`实际下发 ${r.hit_count??0} 次 · 来源 ${r.created_by||'—'}`),
    node('div',{class:'actions'},button('编辑',()=>ruleForm(r)),button('版本记录',()=>versions(r)),r.priority==='P0'?button('配置检查策略',()=>policyForm(r)):null,
      r.status==='draft'?button('审阅通过并启用',()=>send(`/api/rules/${id(r.id)}/status?status=active&expected_version=${r.version}`,'PATCH').then(refresh)):null,
      r.status==='active'?button('停用',async()=>{if(!confirm('停用后，此规则将退出后续上下文。确认停用？'))return;await send(`/api/rules/${id(r.id)}/status?status=revoked&expected_version=${r.version}`,'PATCH');await refresh();}):null));
}
function rulesView(content){
  const grid=node('div',{class:'grid'});function draw(){const rules=state.rules.filter(r=>(state.ruleFilter==='all'||r.status===state.ruleFilter)&&json([r.title,r.scope_patterns,r.content_points]).toLowerCase().includes(state.ruleTerm.toLowerCase()));grid.replaceChildren(...rules.map(r=>ruleCard(r)));if(!rules.length)grid.append(empty('此范围暂无规则。创建规则，或通过 PRD 分析生成待审候选。'));}
  const filter=node('select',{'aria-label':'规则状态',onchange:e=>{state.ruleFilter=e.target.value;draw();}},[['active','已启用'],['draft','待审候选'],['all','全部状态']].map(([value,label])=>node('option',{value},label)));filter.value=state.ruleFilter;
  content.append(node('div',{class:'toolbar'},button('＋ 新建规则',()=>ruleForm(null),'primary'),button('分析需求',()=>navigate('analysis')),filter,node('input',{placeholder:'按标题、范围或条款筛选',value:state.ruleTerm,'aria-label':'筛选规则',oninput:e=>{state.ruleTerm=e.target.value;draw();}})),grid);draw();
}
function createTask(){form('新建任务',[{key:'title',label:'标题'},{key:'description',label:'需求说明',multiline:true,required:false}],d=>send(projectPath('tasks'),'POST',d));}
async function taskStatus(task,status){if(['released','archived'].includes(status)&&!confirm('这会停用该任务的短期规则，并保留历史。是否继续？'))return;await send(`/api/tasks/${id(task.id)}/status?status=${status}`,'PATCH');await refresh();}
function tasksView(content){
  content.append(node('div',{class:'toolbar'},button('＋ 新建任务',createTask,'primary'),button('PRD 分析与候选',()=>navigate('analysis')),node('span',{class:'muted'},'发布 / 归档后短期规则退出；暂停保留内容，恢复后重新参与上下文。')));
  const lanes=node('div',{class:'swimlanes','aria-label':'需求泳道'});
  for(const [status,label] of Object.entries(taskLabels)){
    const tasks=state.tasks.filter(t=>t.status===status),lane=node('section',{class:'lane','data-status':status},node('div',{class:'lane-head'},node('h2',{},label),tag(tasks.length)));
    for(const task of tasks){const rules=state.rules.filter(r=>r.task_id===task.id),active=rules.filter(r=>r.status==='active'),scopes=[...new Set(rules.flatMap(r=>r.scope_patterns))];
      const actions=node('div',{class:'actions'});
      if(['active','testing'].includes(status))actions.append(button('暂停',()=>send(`/api/tasks/${id(task.id)}/pause`,'PATCH',{reason:'工作台人工暂停'}).then(refresh)));
      if(status==='paused')actions.append(button('恢复',()=>send(`/api/tasks/${id(task.id)}/resume`,'PATCH',{reason:'工作台人工恢复'}).then(refresh)));
      if(status==='draft')actions.append(button('开始',()=>taskStatus(task,'active')));
      if(status==='active')actions.append(button('进入验证',()=>taskStatus(task,'testing')));
      if(status==='testing')actions.append(button('返回开发',()=>taskStatus(task,'active')),button('已发布',()=>taskStatus(task,'released')));
      if(!['released','archived'].includes(status))actions.append(button('已归档',()=>taskStatus(task,'archived')));
      if(['released','archived'].includes(status))actions.append(button('提炼长期记忆',()=>startDistill(task.id)));
      lane.append(node('article',{class:'card','data-task-id':task.id},tag(label,status),node('h3',{style:'margin-top:10px'},task.title),node('p',{class:'task-description'},task.description||'尚未填写需求说明。'),node('div',{class:'tags'},tag(`${active.length} 活跃 / ${rules.length} 规则`),tag(`${scopes.length} 文件范围`)),scopes.length?code(scopes.slice(0,3).join(' · ')):null,button('查看范围与规则',()=>details(task.title,node('p',{},task.description),code(task.id),rules.length?rules.map(r=>ruleCard(r)):empty('尚无绑定规则。可在 PRD 分析页生成候选。')),'link'),actions));
    }
    if(!tasks.length)lane.append(empty('此泳道暂无需求',true));lanes.append(lane);
  }
  content.append(lanes);
}
function contextView(content){
  const path=node('input',{placeholder:'输入实际工作区相对文件路径',value:state.path,'aria-label':'预览文件路径'}),task=node('select',{'aria-label':'预览任务'},taskOptions(true,true).map(([value,label])=>node('option',{value},label))),out=node('pre',{},'选择任务并输入文件路径。');task.value=state.task;
  content.append(node('div',{class:'toolbar'},path,task,button('预览上下文',async()=>{const q=new URLSearchParams({project_id:state.project,file_path:path.value});if(task.value)q.set('task_id',task.value);const data=await api('/api/context?'+q);out.textContent=data.rendered_markdown||'此范围暂无可用规则。';},'primary')),out,node('p',{},'预览不会产生下发凭据。真实 Agent 会话的上下文下发和 Debug 评分可在「代码与上下文」及「反馈与问题」追踪。'));
}
function table(headers,rows){return node('div',{class:'table-wrap'},node('table',{},node('thead',{},node('tr',{},headers.map(h=>node('th',{scope:'col'},h)))),node('tbody',{},rows.map(cells=>node('tr',{},cells.map(c=>node('td',{},c)))))));}
function fileButton(path,line){return button(path+(line?':'+line:''),async()=>{$('detail').close();state.path=path;await navigate('explorer');},'link');}
function definition(entries){return node('dl',{class:'definition'},entries.flatMap(([label,value])=>[node('dt',{},label),node('dd',{},value??'—')]));}
async function explorerView(content){
  const task=node('select',{'aria-label':'目录任务范围',onchange:e=>{state.task=e.target.value;refresh();}},taskOptions(true,true).map(([value,label])=>node('option',{value},label)));task.value=state.task;
  const workspace=node('select',{'aria-label':'代码索引工作区',onchange:e=>{state.worktree=e.target.value;refresh();}},workspaceOptions().map(([value,label])=>node('option',{value},label)));workspace.value=state.worktree;
  content.append(node('div',{class:'toolbar'},task,workspace,button('更新代码索引',()=>indexWorkspace()),button('＋ 当前文件规则',()=>ruleForm(null,state.path||'**'))));
  const treePane=node('div',{class:'tree-pane'}),focus=node('div',{class:'focus-pane',id:'focus-inspector'}),treeContent=node('div',{class:'tree-content','aria-label':'代码目录'});
  const search=node('input',{placeholder:'筛选目录或文件…','aria-label':'筛选代码目录'});
  treePane.append(node('div',{class:'pane-title'},node('h2',{},'Repository scopes'),tag('真实文件')),node('div',{class:'tree-filter'},search),treeContent,node('div',{class:'tree-legend'},node('span',{},'P0 / P1 约束'),node('span',{},'L 长期契约'),node('span',{},'T 活跃需求')));
  content.append(node('div',{class:'split-view'},treePane,focus));
  const query=new URLSearchParams();if(state.task)query.set('task_id',state.task);if(state.worktree)query.set('worktree_id',state.worktree);
  const viewProject=state.project;const data=await api(projectPath('tree')+(query.size?'?'+query:''));if(state.project!==viewProject)return;const root=data.tree;state.files=[];
  const collect=n=>{if(n.type==='file')state.files.push(n.path);for(const c of n.children||[])collect(c);};if(root)collect(root);
  function counts(n){const activeTask=state.tasks.find(t=>t.id===state.task);const rules=(n.rules||[]).map(r=>state.rules.find(full=>full.id===r.id)||r).filter(r=>r.status==='active'&&(r.lifecycle==='long_term'||(r.task_id===state.task&&['active','testing'].includes(activeTask?.status))));const long=rules.filter(r=>r.lifecycle==='long_term').length,tasks=new Set(rules.filter(r=>r.lifecycle==='short_term'&&r.task_id).map(r=>r.task_id)).size,p0=rules.filter(r=>r.priority==='P0').length,p1=rules.filter(r=>r.priority==='P1').length;return node('span',{class:'tree-counts'},p0?node('span',{class:'p0'},'P0 '+p0):null,p1?node('span',{class:'p1'},'P1 '+p1):null,long?node('span',{class:'long'},'L '+long):null,tasks?node('span',{class:'task'},'T '+tasks):null);}
  function renderTree(n,term,depth=0){
    const children=(n.children||[]).map(c=>renderTree(c,term,depth+1)).filter(Boolean),matches=n.path.toLowerCase().includes(term);
    if(term&&!matches&&!children.length)return null;
    if(n.type==='file')return button([node('span',{'aria-hidden':'true'},'·'),node('span',{class:'tree-name'},n.name),counts(n)],async()=>{state.path=n.path;draw();await inspect(n.path,focus);},'tree-file'+(state.path===n.path?' selected':''),{'data-path':n.path,title:n.path,draggable:true,ondragstart:e=>e.dataTransfer.setData('text/plain',n.path)});
    const isOpen=term||depth<1||state.openDirs.has(n.path);const d=node('details',{open:!!isOpen,ontoggle:e=>{if(e.target.open)state.openDirs.add(n.path);else state.openDirs.delete(n.path);}},node('summary',{},node('span',{class:'tree-name'},n.name),counts(n)),node('div',{class:'tree-children'},children));return d;
  }
  function draw(){treeContent.replaceChildren();if(root&&state.files.length){const rendered=renderTree(root,search.value.toLowerCase());treeContent.append(rendered||empty('没有匹配的文件。',true));}else treeContent.append(empty('尚无可浏览的文件。选择已注册工作区并建立索引；远程工作区由客户端上传代码清单。',true));}
  search.oninput=draw;draw();
  if(state.path)await inspect(state.path,focus);else focus.append(empty('从左侧选择一个文件，查看继承的规则、代码实体与过去 7 天的真实 Agent 下发。'));
}
let inspectGeneration=0;
async function inspect(path,container){
  const generation=++inspectGeneration;container.replaceChildren(node('div',{class:'skeleton','aria-label':'正在加载文件详情'}));
  const q=new URLSearchParams({path,days:'7'});if(state.task)q.set('task_id',state.task);if(state.worktree)q.set('worktree_id',state.worktree);
  try{
    const data=await api(projectPath('inspector')+'?'+q);if(generation!==inspectGeneration)return;
    container.replaceChildren(node('div',{class:'caption'},'FOCUS INSPECTOR'),node('div',{class:'focus-path'},path),node('div',{class:'breadcrumbs'},path.split('/').map(p=>node('span',{},p))),node('p',{class:'muted'},'任务范围：'+taskName(state.task)+' · 最近 7 天 · 预览不计入下发'));
    const rules=data.rules||[];container.append(section('继承与匹配规则',rules.length+' 条'));
    if(!rules.length)container.append(empty('此文件在当前任务中没有匹配规则。',true));
    for(const item of rules){const r=item.rule||item;const card=ruleCard(r,true);card.append(definition([['匹配范围',(item.matched_scopes||r.matched_scopes||r.scope_patterns||[]).join(' → ')],['继承说明',typeof item.inheritance==='string'?item.inheritance:json(item.inheritance||r.inheritance||'按文件范围匹配')],['来源',typeof item.source==='string'?item.source:json(item.source||r.created_by||'—')],['任务',taskName(r.task_id)],['版本',`v${r.version} · ${time(r.updated_at)}`]]));container.append(card);}
    container.append(section('过去 7 天 Agent 下发'));
    const stats=data.agent_stats||[];
    if(stats.length)container.append(table(['Agent','下发次数','最近下发'],stats.map(s=>[s.agent_name||s.agent_client||s.agent||'—',s.deliveries??s.delivery_count??s.count??0,time(s.last_seen||s.last_seen_at||s.last_delivery_at)])));
    const deliveries=data.deliveries||[];
    if(deliveries.length)container.append(node('details',{},node('summary',{},`展开 ${deliveries.length} 条真实下发凭据`),deliveries.map(d=>node('div',{class:'row'},code(d.delivery_id||d.id),node('p',{class:'muted'},`${d.agent_name||d.agent_client||d.session_id} · ${time(d.created_at)}`),code('任务 '+taskName(d.task_id)),node('details',{},node('summary',{},'下发内容 / 凭据详情'),node('pre',{},d.rendered_markdown||json(d)))))));
    if(!deliveries.length&&!stats.length)container.append(empty('过去 7 天此文件没有已记录的 Agent 下发。',true));
    const graphPane=node('div');container.append(section('代码实体与关联证据'),graphPane);
    try{const graph=await api(projectPath('graph')+'?'+q);if(generation!==inspectGeneration)return;const entities=graph.entities||[],edges=graph.edges||[];graphPane.append(node('p',{class:'muted'},`索引 ${graph.snapshot_id||'—'} · ${entities.length} 个实体 · ${edges.length} 条关联`));
      if(entities.length)graphPane.append(table(['实体','类型','证据位置'],entities.map(e=>[e.name||e.qualified_name||e.id,e.kind||e.type,fileButton(e.path||path,e.line||e.start_line)])));
      if(edges.length)graphPane.append(node('details',{},node('summary',{},'查看依赖 / 接口关联'),edges.map(e=>node('div',{class:'row'},code(`${e.source||e.source_id||e.from} → ${e.target||e.target_id||e.to}`),node('p',{class:'muted'},e.kind||e.type),e.evidence?code(json(e.evidence)):null))));
      if(!entities.length&&!edges.length)graphPane.append(empty('此文件尚无已索引实体或关联。',true));
      if(graph.limitations?.length)graphPane.append(node('p',{class:'muted'},'索引边界：'+graph.limitations.join('；')));
    }catch(error){graphPane.append(errorPanel(error,()=>inspect(path,container)));}
  }catch(error){if(generation===inspectGeneration)container.replaceChildren(errorPanel(error,()=>inspect(path,container)));}
}
async function indexWorkspace(){
  const choices=state.workspaces.filter(w=>w.source!=='remote');
  if(!choices.length){details('建立代码索引',node('p',{},'尚无可在 Hub 本机索引的工作区。请先连接实际客户端；远程工作区通过客户端上传清单和代码结构。'));return;}
  form('更新代码索引',[{key:'worktree_id',label:'Hub 本机已注册工作区',options:choices.map(w=>[w.id,w.machine_name+' · '+w.worktree_path]),value:state.worktree||choices[0].id}],async d=>{await send(projectPath('index/local'),'POST',{worktree_id:d.worktree_id});state.worktree=d.worktree_id;notice('代码索引已更新。后续分析将引用该索引中的文件证据。');},'建立索引');
}
async function startDistill(taskId){
  form('提炼需求中的长期记忆',[{note:'提交后会生成可审阅建议。批准之前不会改变项目长期契约。'},{key:'task_id',label:'需求',options:taskOptions(false,true),value:taskId},{key:'worktree_id',label:'代码工作区',options:workspaceOptions(),value:state.worktree}],async d=>{const job=await send(projectPath('distill'),'POST',{task_id:d.task_id,request_id:requestId(),...(d.worktree_id?{worktree_id:d.worktree_id}:{})});state.job=job.id;state.tab='analysis';},'生成提炼建议');
}
async function analysisView(content){
  content.append(node('div',{class:'toolbar'},button('＋ 分析 PRD',()=>form('根据代码分析需求',[
    {note:'模型将结合项目代码索引提出文件范围和优先级。请先建立索引；服务未配置分析模型时，任务会明确报告失败原因。'},
    {key:'task_id',label:'关联需求',options:taskOptions(false)},
    {key:'worktree_id',label:'代码工作区',options:workspaceOptions(),value:state.worktree},
    {key:'text',label:'PRD / 业务意图',multiline:true,help:'可以直接描述预期行为，无需预先猜测文件路径。'}
  ],async d=>{if(!d.task_id)throw new Error('请先创建需求。');const job=await send(projectPath('analysis'),'POST',{task_id:d.task_id,text:d.text,request_id:requestId(),...(d.worktree_id?{worktree_id:d.worktree_id}:{})});state.job=job.id;},'开始分析'),'primary'),button('更新代码索引',indexWorkspace),button('提炼长期记忆',()=>startDistill(state.task)),button('＋ 新建任务',createTask)));
  const jobsResponse=await api(projectPath('analysis/jobs')),jobs=Array.isArray(jobsResponse)?jobsResponse:jobsResponse.jobs||[];
  if(!jobs.length){content.append(empty('尚无分析任务。建立真实代码索引后，输入 PRD；分析、失败重试和人工审阅都将保留记录。'));return;}
  if(!jobs.some(j=>j.id===state.job))state.job=jobs[0].id;
  const list=node('div',{class:'job-list'}),detail=node('div',{class:'panel'});
  async function selectJob(jobId){state.job=jobId;for(const b of list.querySelectorAll('button'))b.classList.toggle('selected',b.dataset.jobId===jobId);detail.replaceChildren(node('div',{class:'skeleton'}));try{const job=await api('/api/analysis/jobs/'+id(jobId));if(state.job===jobId)renderJob(job,detail);}catch(error){detail.replaceChildren(errorPanel(error,()=>selectJob(jobId)));}}
  for(const j of jobs)list.append(button([node('div',{class:'card-top'},node('strong',{},j.kind==='distill'?'长期记忆提炼':'PRD 分析'),tag(j.status,j.status)),node('p',{},taskName(j.task_id)),code(time(j.created_at)),code(j.id)],()=>selectJob(j.id),j.id===state.job?'selected':'',{'data-job-id':j.id}));
  content.append(node('div',{class:'job-grid'},list,detail));await selectJob(state.job);
}
function renderJob(job,container){
  container.replaceChildren(node('div',{class:'card-top'},node('h2',{},job.kind==='distill'?'提炼建议':'需求分析结果'),tag(job.status,job.status)),definition([['关联需求',taskName(job.task_id)],['任务 ID',job.id],['代码索引',job.snapshot_id||job.result?.snapshot_id||'—'],['创建时间',time(job.created_at)],['完成时间',time(job.completed_at)]]));
  if(job.error)container.append(node('div',{class:'error-panel'},node('strong',{},'分析未完成'),node('p',{},typeof job.error==='string'?job.error:json(job.error)),button('重试分析',async()=>{const updated=await send(`/api/analysis/jobs/${id(job.id)}/retry`,'POST');state.job=updated.id||job.id;await refresh();})));
  if(['queued','running','pending'].includes(job.status))container.append(node('p',{class:'muted'},'任务正在等待或执行。实时流连接时会自动更新；刷新也可查看最新状态。'));
  if(job.result?.summary)container.append(node('p',{},job.result.summary));
  if(job.result?.limitations?.length)container.append(node('p',{class:'muted'},'分析边界：'+job.result.limitations.join('；')));
  const candidates=job.candidates||job.result?.candidates||[];
  for(const c of candidates){container.append(node('article',{class:'card candidate','data-candidate-id':c.id},node('div',{class:'card-top'},node('h3',{},c.title),tag(c.priority,c.priority?.toLowerCase())),node('div',{class:'tags'},tag(c.status,c.status),tag(c.action==='merge'?'合并现有契约':c.action==='discard'?'建议丢弃':'新建规则')),code((c.scope_patterns||[]).join(' · ')),node('ul',{},(c.content_points||[]).map(p=>node('li',{},p))),node('p',{},c.rationale||''),c.target_rule_id?code(`合并目标 ${c.target_rule_id} · v${c.target_rule_version??'—'}`):null,node('div',{class:'evidence'},(c.evidence||[]).map(e=>fileButton(e.path,e.line))),c.status==='pending'?node('div',{class:'actions'},button('审阅并批准',()=>reviewCandidate(c)),button('拒绝候选',async()=>{await send(`/api/analysis/candidates/${id(c.id)}/review`,'POST',{action:'reject',expected_version:c.version});await refresh();})):null));}
  if(job.status==='completed'&&!candidates.length)container.append(empty('本次分析没有产生候选。查看原始结果了解原因；没有规则被自动新增。',true));
  if(job.result)container.append(node('details',{},node('summary',{},'查看完整分析结果与来源'),node('pre',{},json(job.result))));
}
function reviewCandidate(c){
  form('审阅候选 · '+c.title,[{note:`处理方式：${c.action}。请核对代码证据和文件范围。批准会生成规则变更记录。`},{key:'title',label:'标题',value:c.title},{key:'priority',label:'优先级',options:[['P0','P0'],['P1','P1'],['P2','P2']],value:c.priority},{key:'scopes',label:'文件范围 · 每行一项',multiline:true,value:(c.scope_patterns||[]).join('\n'),help:'可从代码目录拖入文件路径；保存前仍可调整为适当 Glob。'},{key:'points',label:'条款 · 每行一项',multiline:true,value:(c.content_points||[]).join('\n')}],d=>send(`/api/analysis/candidates/${id(c.id)}/review`,'POST',{action:'approve',expected_version:c.version,title:d.title,scope_patterns:lines(d.scopes),priority:d.priority,content_points:lines(d.points)}),'批准候选');
  const scopes=$('editor-fields').querySelector('[name=scopes]');mountScopePicker(scopes);scopes.ondragover=e=>e.preventDefault();scopes.ondrop=e=>{e.preventDefault();const path=e.dataTransfer.getData('text/plain').trim();if(path&&!path.includes('\n')&&!path.startsWith('/')&&!path.split('/').includes('..'))scopes.value=[...new Set([...lines(scopes.value),path])].join('\n');};
}
async function mountScopePicker(scopes){
  const panel=node('details',{},node('summary',{},'从真实目录添加文件范围'));
  const search=node('input',{placeholder:'筛选路径…','aria-label':'候选文件范围搜索'}),list=node('div',{class:'scope-picker'});
  panel.append(node('p',{class:'muted'},'点击文件添加；也可将路径拖到上方范围输入框。只在批准候选时保存。'),search,list);scopes.closest('label').after(panel);
  try{const query=state.worktree?'?worktree_id='+id(state.worktree):'';const data=await api(projectPath('tree')+query),files=[];function visit(n){if(n.type==='file')files.push(n.path);for(const child of n.children||[])visit(child);}if(data.tree)visit(data.tree);
    const add=path=>{scopes.value=[...new Set([...lines(scopes.value),path])].join('\n');draw();};
    function draw(){const matching=files.filter(path=>path.toLowerCase().includes(search.value.toLowerCase()));list.replaceChildren(...matching.slice(0,120).map(path=>button(path,()=>add(path),'scope-choice'+(lines(scopes.value).includes(path)?' selected':''),{draggable:true,ondragstart:e=>e.dataTransfer.setData('text/plain',path)})));if(!matching.length)list.append(empty('此索引没有匹配文件。',true));if(matching.length>120)list.append(node('p',{class:'muted'},`共 ${matching.length} 个匹配文件，继续筛选以缩小范围。`));}search.oninput=draw;draw();
  }catch(error){list.append(errorPanel(error));}
}
async function workspaceView(content){
  const workspaces=state.workspaces,sessions=state.sessions;
  content.append(node('div',{class:'toolbar'},button('连接办公机 / Agent',connectionForm,'primary'),button('管理客户端授权',clientAccess)));
  content.append(node('p',{class:'muted'},'最近在线按服务端心跳窗口判断。工作区默认任务与已运行会话的任务分别显示；会话换绑需要匹配当前绑定版本。'));
  if(!workspaces.length)content.append(empty('尚无工作区客户端注册。连接 MCP / 客户端后，实际机器、路径、分支与心跳会显示在这里。'));
  const grid=node('div',{class:'grid'});
  for(const w of workspaces){const own=sessions.filter(s=>s.worktree_id===w.id);grid.append(node('article',{class:'card','data-worktree-id':w.id},node('div',{class:'card-top'},node('h3',{},w.machine_name),tag(w.is_online?'最近在线':'心跳已过期',w.is_online?'online':'')),code(w.worktree_path),definition([['客户端',w.agent_client],['分支',w.git_branch],['提交',w.git_commit||'尚未上报'],['默认任务',taskName(w.active_task_id)],['当前文件',w.current_file?fileButton(w.current_file):'尚未上报'],['最后心跳',time(w.last_heartbeat)],['来源',w.source]]),node('p',{class:'muted'},`${own.filter(s=>s.state==='active').length} 个活跃会话 / ${own.length} 个已记录会话`),button('修改工作区默认任务',()=>form('工作区默认任务',[{note:'此设置影响工作区默认绑定。正在运行的会话仍保留自己的任务；可在下方会话中单独换绑。'},{key:'task_id',label:'默认任务',options:taskOptions(),value:w.active_task_id||''}],d=>send(`/api/worktrees/${id(w.id)}/bind-task`,'POST',{task_id:d.task_id||null})))));}
  content.append(grid,section('运行会话',`${sessions.length} 个真实会话`));
  if(!sessions.length){content.append(empty('尚无会话记录。客户端注册会话后才会产生上下文凭据。',true));return;}
  for(const s of sessions){const latest=s.latest_delivery;content.append(node('article',{class:'card section','data-session-id':s.id},node('div',{class:'card-top'},node('h3',{},s.agent_client),tag(s.state,s.state)),code(s.id),definition([['任务',taskName(s.task_id)],['绑定版本',s.binding_revision??0],['最近活动',time(s.last_seen_at)],['当前文件',s.current_file?fileButton(s.current_file):latest?.file_path?fileButton(latest.file_path):'尚无下发'],['工作区',s.worktree_id]]),latest?node('details',{},node('summary',{},'最近一次上下文下发'),code(latest.delivery_id||latest.id),node('pre',{},latest.rendered_markdown||json(latest))):node('p',{class:'muted'},'此会话尚无已记录的上下文下发。'),s.state==='active'?button('安全换绑任务',()=>form('会话任务换绑',[{note:`在下一次上下文获取前生效；当前绑定版本为 ${s.binding_revision??0}。如果客户端同时修改绑定，服务将拒绝覆盖。`},{key:'task_id',label:'新任务',options:taskOptions(),value:s.task_id||''}],d=>send(`/api/agent/sessions/${id(s.id)}/bind-task`,'POST',{task_id:d.task_id||null,expected_revision:s.binding_revision??0}))):null));}
}
function policyForm(rule){
  form('检查策略 · '+rule.title,[{note:'策略绑定此规则的当前版本。以下为明确、可执行的检查条件；自然语言契约由语义检查另行评估。规则更新后需重新审阅策略。'},
    {key:'kind',label:'检查条件',options:[['forbid_path_changes','禁止修改匹配文件'],['forbid_added_literal','禁止新增指定文本'],['require_added_literal','匹配变更需包含指定新增文本']]},
    {key:'paths',label:'检查文件范围 · 每行一项',multiline:true,value:rule.scope_patterns.join('\n')},
    {key:'literal',label:'指定文本（文件修改禁令可留空）',multiline:true,required:false}
  ],d=>send(`/api/rules/${id(rule.id)}/policy`,'POST',{expected_version:rule.version,reviewed:true,reviewer:'human',spec:{kind:d.kind,paths:lines(d.paths),...(d.kind==='forbid_path_changes'?{}:{literal:d.literal})}}),'审阅并绑定策略');
}
async function semanticPanel(content){
  content.append(section('语义冲突审阅','模型判断与结构事实分开保留'));
  const output=node('div');content.append(node('div',{class:'toolbar'},button('分析当前规则语义',async()=>{notice('正在根据代码证据和现有条款审阅语义冲突…');await send(projectPath('diagnostics/semantic'),'POST',state.worktree?{worktree_id:state.worktree}:{});notice('语义审阅完成。结果是带证据的模型判断，需结合实际需求复核。');await refresh();})),output);
  try{const response=await api(projectPath('diagnostics/semantic'));const results=Array.isArray(response)?response:response.results||[];
    if(!results.length){output.append(empty('尚无语义审阅记录。点击分析后，将核对可同时生效且范围重叠的条款。',true));return;}
    for(const result of results)output.append(node('details',{},node('summary',{},`${time(result.created_at)} · ${(result.conflicts||[]).length} 项模型提示`),node('p',{},result.summary),code('提供方 '+json(result.provider)+' · 索引 '+(result.snapshot_id||'—')),node('p',{class:'muted'},(result.limitations||[]).join('；')),(result.conflicts||[]).map(c=>node('article',{class:'card section'},node('div',{class:'card-top'},node('h3',{},c.title),tag(c.severity,'warning')),node('p',{},c.reasoning),(c.clauses||[]).map(clause=>node('blockquote',{},code(clause.rule_id+' · v'+clause.rule_version),node('p',{},clause.excerpt))),node('div',{class:'evidence'},(c.evidence||[]).map(e=>fileButton(e.path,e.line))),node('p',{},c.suggested_resolution)))));
  }catch(error){output.append(errorPanel(error,refresh));}
}
async function reviewView(content){
  const results=await Promise.allSettled([api(projectPath('governance')),api(projectPath('findings')),api(projectPath('proposals')),api(projectPath('health-check'))]);
  content.append(node('div',{class:'toolbar'},button('＋ 提交治理变更',()=>proposalForm()),button('提炼长期记忆',()=>startDistill(state.task))));
  const gov=results[0].status==='fulfilled'?results[0].value:null,findings=results[1].status==='fulfilled'?results[1].value:[],legacy=results[2].status==='fulfilled'?results[2].value:[],health=results[3].status==='fulfilled'?results[3].value:null;
  for(const [i,r] of results.entries())if(r.status==='rejected')content.append(errorPanel(new Error(['治理数据','发现记录','契约提案','结构检查'][i]+'：'+r.reason.message),refresh));
  if(gov){
    const rules=gov.rules||[];content.append(section('规则证据与老化','置信度来源于观测记录；不等于正确率'));
    if(rules.length)content.append(table(['规则 / 当前版本','观测阶段','有效置信度','支持 / 反例','最后观测','老化提示','证据'],rules.map(r=>[
      node('div',{},node('strong',{},r.title),code(r.rule_id+' · v'+r.version)),tag(r.stage,r.stage),r.effective_confidence==null?'—':Number(r.effective_confidence).toFixed(3),`${r.support_count??0} / ${r.contradiction_count??0}`,time(r.last_observed_at),r.stale?tag('建议复核','warning'):r.age_days!=null?`${Number(r.age_days).toFixed(1)} 天`:'—',button('查看证据',()=>details(r.title,definition([['观测置信度',r.confidence],['衰减后',r.effective_confidence],['半衰期',r.half_life_days==null?'—':r.half_life_days+' 天']]),(r.observations||[]).length?(r.observations||[]).map(o=>node('div',{class:'row'},tag(o.supports?'支持':'反例',o.supports?'online':'warning'),node('p',{},o.reason),code('测试 '+o.test_run_id+' · v'+o.rule_version),code(time(o.created_at)))):empty('暂无带测试证据的观测。',true)))])));
    else content.append(empty('尚无可治理的规则。创建规则或通过真实 Agent 会话记录观测后查看证据。',true));
    content.append(section('结构化变更提案','批准前核对目标版本、变更内容和来源'));
    const proposals=gov.proposals||[];
    if(!proposals.length)content.append(empty('暂无治理提案。',true));
    for(const p of proposals)content.append(node('article',{class:'card section'},node('div',{class:'card-top'},node('h3',{},p.reason||p.id),tag(p.status,p.status)),code(time(p.created_at)),node('pre',{},json(p.change)),node('details',{},node('summary',{},'来源证据'),node('pre',{},json(p.source_refs||[]))),p.status==='pending'?node('div',{class:'actions'},button('审阅并应用变更',()=>form('批准结构化提案',[{note:'将原子地执行上方提案中的具体变更；目标版本不一致时会拒绝应用。'},{key:'reason',label:'审阅意见',value:'已核对规则范围与来源证据'}],d=>send(`/api/governance/proposals/${id(p.id)}/apply`,'POST',{reviewed:true,reviewer:'human',reason:d.reason})), 'primary'),button('拒绝提案',()=>form('拒绝治理提案',[{key:'reason',label:'拒绝原因'}],d=>send(`/api/governance/proposals/${id(p.id)}/reject`,'POST',{reviewer:'human',reason:d.reason}),'确认拒绝'))):null));
    content.append(section('失败反射与会话整理'));
    const reflections=gov.reflections||[];
    if(reflections.length)content.append(reflections.map(r=>node('details',{},node('summary',{},r.title||r.summary||r.reason||r.id),node('pre',{},json(r)))));else content.append(empty('尚无真实测试失败触发的反射记录。',true));
    if(gov.distillation_requests?.length)content.append(node('details',{},node('summary',{},'提炼请求记录'),node('pre',{},json(gov.distillation_requests))));
  }
  content.append(section('待审发现',`${findings.filter(f=>f.status==='pending_review').length} 条`));
  const pending=findings.filter(f=>f.status==='pending_review');if(!pending.length)content.append(empty('暂无待审发现。',true));
  content.append(node('div',{class:'grid'},pending.map(f=>node('article',{class:'card'},fileButton(f.target_path),node('p',{},f.finding_text),tag(f.source),code(f.session_id||'人工记录'),code(time(f.created_at)),button('审阅并晋升长期规则',()=>form('审阅发现',[{key:'title',label:'规则标题'},{key:'scope',label:'范围',value:f.target_path},{key:'priority',label:'优先级',options:[['P0','P0'],['P1','P1'],['P2','P2']],value:f.suggested_priority}],d=>send(`/api/findings/${id(f.id)}/crystallize`,'POST',{title:d.title,scope_patterns:lines(d.scope),lifecycle:'long_term',priority:d.priority})))))));
  const pendingLegacy=legacy.filter(p=>p.status==='pending');if(pendingLegacy.length)content.append(section('契约提案'),node('div',{class:'grid'},pendingLegacy.map(p=>node('article',{class:'card'},code(p.target_component),node('p',{},p.proposed_contract),node('p',{},p.justification),button('审阅并批准',async()=>{if(!confirm('已审阅此契约及其适用范围，批准为长期规则？'))return;await send(`/api/proposals/${id(p.id)}/approve`,'POST');await refresh();})))));
  if(health){content.append(section('全库结构诊断'),node('p',{class:'muted'},health.assessment_scope||'以下为结构提示，需要结合实际代码和规则语义审阅。'));
    if(!health.conflicts?.length)content.append(empty('本次结构检查没有报告问题。语义矛盾和代码正确性仍需结合具体证据验证。',true));
    for(const c of health.conflicts||[])content.append(node('article',{class:'card section'},node('div',{class:'card-top'},node('h3',{},c.title),tag(c.severity,c.severity==='critical'?'noise':'warning')),tag(c.conflict_type),node('p',{},c.description),code((c.involved_rule_ids||[]).join(' · ')),node('p',{},c.suggested_fix)));
  }
  await semanticPanel(content);
}
function changeFields(initial={}){return [
  {key:'action',label:'具体操作',options:[['update','更新规则'],['revoke','停用规则'],['create','新增长期契约'],['merge','合并规则']],value:initial.action||'update'},
  {key:'rule_id',label:'目标规则（新建时不使用）',options:[['','请选择'],...state.rules.map(r=>[r.id,`${r.title} · v${r.version}`])],value:initial.rule_id||''},
  {key:'title',label:'规则标题',required:false,value:initial.title||''},{key:'priority',label:'优先级',options:[['','保留当前'],['P0','P0'],['P1','P1'],['P2','P2']],value:initial.priority||''},
  {key:'scopes',label:'文件范围 · 每行一项',multiline:true,required:false,value:(initial.scope_patterns||[]).join('\n')},
  {key:'points',label:'具体条款 · 每行一项',multiline:true,required:false,value:(initial.content_points||[]).join('\n')},
  {key:'source_rule_ids',label:'合并来源规则 ID · 每行一项',multiline:true,required:false,value:(initial.source_rule_ids||[]).join('\n')},
  {key:'reason',label:'审阅依据 / 变更原因'}
];}
function reviewedChange(d){const change={action:d.action},rule=state.rules.find(r=>r.id===d.rule_id);
  if(d.action!=='create'){if(!rule)throw new Error('请选择目标规则。');change.rule_id=rule.id;change.expected_version=rule.version;}
  if(d.title)change.title=d.title;if(d.priority)change.priority=d.priority;if(d.scopes)change.scope_patterns=lines(d.scopes);if(d.points)change.content_points=lines(d.points);if(d.source_rule_ids)change.source_rule_ids=lines(d.source_rule_ids);
  if(d.action==='create'&&(!d.title||!d.scopes||!d.points))throw new Error('新建规则必须填写标题、文件范围和条款。');return change;
}
function proposalForm(){form('提交结构化治理提案',[{note:'提案提交后需要审阅并应用。更新已有规则时使用当前版本进行并发校验。'},...changeFields()],d=>send(projectPath('governance/proposals'),'POST',{reason:d.reason,change:reviewedChange(d),source_refs:[]}),'提交提案');}
function issueReview(issue){let suggestion={};try{suggestion=JSON.parse(issue.suggested_action||'{}');}catch{/* Free text is shown, never executed. */}
  if(!suggestion||typeof suggestion!=='object'||Array.isArray(suggestion))suggestion={};
  form('审阅问题建议 · '+issue.title,[{note:'原始建议：'+(issue.suggested_action||'未提供。请根据问题证据填写具体变更。')},{note:'下方为要应用的结构化变更。规则变更与问题处理在同一事务中完成。'},...changeFields({...suggestion,rule_id:suggestion.rule_id||issue.related_rule_ids?.[0]})],d=>send(`/api/issues/${id(issue.id)}/apply-suggestion`,'POST',{reviewed:true,reviewer:'human',reason:d.reason,change:reviewedChange(d)}),'应用变更并处理问题');
}
async function debugView(content){
  const [quality,evaluations,issues]=await Promise.all([api(projectPath('rule-quality')),api(projectPath('evaluations')+'?limit=1000'),api(projectPath('issues'))]);
  content.append(node('p',{},`载入 ${evaluations.length} 条凭据评分（最近最多 1000 条） · ${issues.filter(i=>i.status==='open').length} 个待处理问题。0 = 已知，1 = 无关，2 = 低质量，3 = 一般，4 = 有帮助，5 = 必不可少。`));
  const matrix=node('div'),filter=node('select',{'aria-label':'反馈信号筛选'},[['all','全部规则版本'],['fatigue','重复 / 疲劳'],['noise','无关 / 噪音'],['unrated','尚无评分']].map(([value,label])=>node('option',{value},label)));
  const groups=new Map();for(const r of state.rules)groups.set(r.id+':'+r.version,{rule:r,version:r.version,evals:[]});
  for(const e of evaluations){const key=e.rule_id+':'+e.rule_version;let g=groups.get(key);if(!g){g={rule:state.rules.find(r=>r.id===e.rule_id)||{id:e.rule_id,title:e.rule_id,priority:'—',scope_patterns:[]},version:e.rule_version,evals:[]};groups.set(key,g);}g.evals.push(e);}
  function evaluationDetail(g){const cells=g.evals.map(e=>[tag(e.score+'/5',e.score<2?'warning':'online'),node('div',{},node('p',{},e.reason||'未填写原因'),fileButton(e.file_path)),code(e.session_id||'—'),code(e.delivery_id||'缺失凭据'),time(e.created_at)]);details(`${g.rule.title} · v${g.version} 的评分`,code(g.rule.scope_patterns.join(' · ')),node('p',{},`${g.evals.length} 个当前载入样本`),cells.length?table(['评分','反馈与文件','会话','下发凭据','时间'],cells):empty('此版本尚无真实评分。',true));}
  function draw(){let rows=[];for(const g of groups.values()){const bins=[0,0,0,0,0,0];for(const e of g.evals)bins[e.score]++;if(filter.value==='fatigue'&&bins[0]<2||filter.value==='noise'&&bins[1]<2||filter.value==='unrated'&&g.evals.length)continue;const avg=g.evals.length?(g.evals.reduce((a,e)=>a+e.score,0)/g.evals.length).toFixed(2):'—';rows.push([node('div',{},button(g.rule.title,()=>evaluationDetail(g),'link'),code('v'+g.version+' · '+g.rule.scope_patterns.join(' · '))),tag(g.rule.priority,g.rule.priority.toLowerCase()),g.evals.length,avg,node('div',{class:'distribution'},bins.map((n,i)=>node('span',{class:'score-cell'+(n?' filled':''),title:`${i} 分：${n} 条`},n))),node('div',{class:'tags'},bins[0]>=2?tag('重复 '+bins[0],'fatigue'):null,bins[1]>=2?tag('无关 '+bins[1],'noise'):null,!g.evals.length?tag('未评分'):null),button('下钻样本',()=>evaluationDetail(g))]);}matrix.replaceChildren(rows.length?table(['规则 / 版本','优先级','样本量','均分','0 / 1 / 2 / 3 / 4 / 5 分','信号','凭据'],rows):empty('此筛选条件下没有规则评分。',true));}
  filter.onchange=draw;content.append(section('规则评分矩阵','按版本分组，不把历史版本均分冒充当前质量'),node('div',{class:'toolbar'},filter),matrix);draw();
  content.append(section('最近 7 天评分趋势','基于当前载入的实际评分时间'));
  const days=Array.from({length:7},(_,i)=>{const d=new Date();d.setHours(0,0,0,0);d.setDate(d.getDate()-6+i);const end=new Date(d);end.setDate(end.getDate()+1);return {d,items:evaluations.filter(e=>{const t=new Date(/Z$|[+-]\d\d:\d\d$/.test(e.created_at)?e.created_at:e.created_at+'Z');return t>=d&&t<end;})};});const max=Math.max(1,...days.map(d=>d.items.length));
  content.append(node('div',{class:'panel'},node('div',{class:'trend'},days.map(({d,items})=>node('div',{class:'trend-day'},node('span',{},items.length),node('div',{class:'trend-bar',style:`height:${items.length/max*65}px`,title:items.length?`均分 ${(items.reduce((n,e)=>n+e.score,0)/items.length).toFixed(2)}`:'无评分'}),node('span',{},`${d.getMonth()+1}/${d.getDate()}`))))));
  content.append(section('Agent 主动问题反馈',`${quality.open_issues_count} 项服务端待处理记录`));
  if(!issues.length)content.append(empty('尚无问题反馈。真实 Agent 会话启用 Debug 后可提交问题与建议。',true));
  for(const issue of issues)content.append(node('article',{class:'card section','data-issue-id':issue.id},node('div',{class:'card-top'},node('h3',{},issue.title),tag(issue.status,issue.status)),tag(issue.issue_type),node('p',{},issue.description),fileButton(issue.file_path),code('会话 '+(issue.session_id||'人工记录')+' · '+time(issue.created_at)),node('details',{open:issue.status==='open'},node('summary',{},'建议与关联规则'),node('pre',{},issue.suggested_action||'没有提供建议动作。'),code((issue.related_rule_ids||[]).join(' · '))),issue.status==='open'?node('div',{class:'actions'},button('审阅并采纳建议',()=>issueReview(issue),'primary'),button('仅标记已解决',async()=>{if(!confirm('确认此问题已通过其他方式解决？此操作不会修改规则。'))return;await send(`/api/issues/${id(issue.id)}/resolve`,'POST');await refresh();})):null));
}
let activityAfter=0;
async function activityView(content){
  const items=await api(projectPath('audit')+`?limit=500&after=${activityAfter}`);
  content.append(node('div',{class:'toolbar'},tag('持久化审计'),node('span',{class:'muted'},`当前页 ${items.length} 条 · 序号大于 ${activityAfter}`),activityAfter?button('回到起始记录',()=>{activityAfter=0;return refresh();}):null,items.length===500?button('后续 500 条',()=>{activityAfter=items.at(-1).sequence;return refresh();}):null));
  if(!items.length){content.append(empty('此范围尚无审计记录。真实规则变更、生命周期和下发事件会显示在这里。'));return;}
  content.append(node('div',{class:'timeline'},items.slice().reverse().map(e=>node('div',{class:'row','data-event-id':e.sequence},node('div',{class:'tags'},tag(e.action),tag('#'+e.sequence)),code(time(e.created_at)+' · '+e.actor),code((e.entity_type?e.entity_type+' · ':'')+e.entity_id),node('details',{},node('summary',{},'查看事件详情'),node('pre',{},typeof e.details==='string'?prettyJSON(e.details):json(e.details)))))));
}
function shellQuote(value){return "'"+value.replaceAll("'", "'\"'\"'")+"'";}
function connectionForm(){
  if(!state.project){showError(new Error('请先选择项目。'));return;}
  form('连接办公机 / Agent',[
    {note:'为当前项目签发独立客户端凭据。工作区保留在办公机，Hub 不会读取 Windows 本地路径。需要 Hub 已启用管理 API Token。'},
    {key:'name',label:'客户端名称',placeholder:'填写可识别的办公机 / Agent 名称'},
    {key:'platform',label:'办公机系统',options:[['windows','Windows · PowerShell'],['linux','Linux / macOS · shell']]},
    {key:'agent',label:'Agent',options:[['Codex','Codex'],['Hermes','Hermes'],['Claude Code','Claude Code'],['pi','pi']]},
    {key:'workspace',label:'该机器的真实工作区绝对路径',help:'例如 Windows 盘符路径或 Linux 绝对路径。此字段只用于生成客户端配置。'},
    {key:'hub',label:'办公机可访问的 Hub 地址',value:location.origin},
    {key:'task',label:'默认需求',options:taskOptions(),value:state.task}
  ],async d=>{let hub;try{hub=new URL(d.hub);if(!['http:','https:'].includes(hub.protocol))throw Error();}catch{throw new Error('Hub 地址必须为 http 或 https URL。');}
    if(d.platform==='windows'&&!/^[A-Za-z]:[\\/]/.test(d.workspace))throw new Error('请输入含盘符的 Windows 工作区绝对路径。');
    if(d.platform!=='windows'&&!d.workspace.startsWith('/'))throw new Error('请输入工作区绝对路径。');
    const client=await send('/api/clients','POST',{name:d.name,project_ids:[state.project]});
    const separator=d.platform==='windows'?'\\':'/',configPath=d.workspace.replace(/[\\/]+$/,'')+separator+'.codeneuro.json';
    const config={hub_url:hub.href.replace(/\/$/,''),project_id:state.project,active_task:d.task||null,token_env:'CODENEURO_TOKEN'};
    const args=['-m','codeneuro.cli','mcp','--config',configPath,'--workspace',d.workspace,'--debug'];
    const cmd='python '+args.map(a=>d.platform==='windows'?"'"+a.replaceAll("'","''")+"'":shellQuote(a)).join(' ');
    const envExample=d.platform==='windows'?"$env:CODENEURO_HUB_URL = '"+config.hub_url.replaceAll("'","''")+"'\n$env:CODENEURO_TOKEN = '<本次客户端 Token>'":'export CODENEURO_HUB_URL='+shellQuote(config.hub_url)+"\nexport CODENEURO_TOKEN='<本次客户端 Token>'";
    details('连接 '+d.agent+' · '+client.name,node('p',{},'客户端凭据仅在此显示一次。保存到办公机的环境变量或安全凭据管理器；关闭此窗口后将清除显示内容。'),node('pre',{'data-sensitive':'true'},client.token),node('p',{},'1. 在办公机安装与 Hub 同版本的 CodeNeuro，并将下列内容保存为：'),code(configPath),node('pre',{},json(config)),node('p',{},'2. 在启动 Agent 的环境中明确固定可信 Hub 并设置凭据。仅凭仓库配置不会发送 Token 或代码；不要把 Token 提交到 Git。'),node('pre',{},envExample),node('p',{},'3. 在 Agent 的 MCP 配置中将下列命令作为本地 stdio 服务。配置字段因宿主而异；python 必须指向安装了 CodeNeuro 的环境。'),node('pre',{},cmd),node('details',{},node('summary',{},'MCP 标准启动参数'),node('pre',{},json({command:'python',args}))),d.agent==='pi'?node('p',{},'pi 若未提供原生 MCP 支持，需要先安装并配置 MCP 适配器，再使用上述标准启动参数。'):null,node('p',{class:'muted'},'Sidecar 在办公机解析本地文件与 Git 身份，通过受认证通道与 Hub 同步。连接后，本页将显示真实会话和下发记录。'),button('我已保存，关闭凭据',()=>$('detail').close()));
    $('detail').dataset.sensitive='true';
  },'签发凭据并生成配置');
}
async function clientAccess(){
  const response=await api('/api/clients'),clients=Array.isArray(response)?response:response.clients||[];
  const own=clients.filter(c=>(c.project_ids||[]).includes(state.project));
  details('当前项目的客户端授权',own.length?own.map(c=>node('div',{class:'row'},node('strong',{},c.name),code(c.id),tag(c.revoked_at||c.revoked?'已撤销':'已授权'),code('创建 '+time(c.created_at)),!c.revoked_at&&!c.revoked?button('撤销此客户端',async()=>{if(!confirm('撤销后此客户端无法继续访问 Hub。确认撤销？'))return;await send('/api/clients/'+id(c.id)+'/revoke','POST');await clientAccess();}):null)):empty('当前项目尚无已签发的客户端凭据。',true));
}
function prettyJSON(text){try{return JSON.stringify(JSON.parse(text),null,2);}catch{return text;}}
function exportForm(){
  const project=state.projects.find(p=>p.id===state.project);if(!project){showError(new Error('请先注册并选择项目。'));return;}
  form('导出静态规则',[
    {note:'导出会更新所选 Hub 本机工作区中的受管规则快照。人工维护内容由导出器保留。远程工作区请使用客户端 sync / watch。'},
    {key:'format',label:'目标格式',options:[['cursor','Cursor .mdc'],['claude','CLAUDE.md']]},
    {key:'task_id',label:'任务范围',options:taskOptions(),value:state.task},
    {key:'out_dir',label:'Hub 本机工作区目录',options:(project.root_paths||[]).map(p=>[p,p])}
  ],async d=>{if(!d.out_dir)throw new Error('此项目没有注册 Hub 本机目录。请在远程工作区运行客户端同步。');const result=await send(projectPath('export'),'POST',{format:d.format,task_id:d.task_id||null,out_dir:d.out_dir});notice('导出完成：'+(result.target_dir||result.target_file)+'\n'+(result.files?result.files.join('\n'):`${result.rules_count} 条规则`));},'写入快照');
}
async function navigate(tab){if(!tabs[tab])return;state.tab=tab;location.hash=tab;await refresh();}
function updateShell(){
  $('title').textContent=tabs[state.tab][0];$('subtitle').textContent=tabs[state.tab][1];$('breadcrumb').textContent=(state.projects.find(p=>p.id===state.project)?.name||'工作区')+' / '+tabs[state.tab][0];
  $('navigation').replaceChildren(...Object.entries(tabs).map(([key,[title,,symbol]])=>button([node('span',{class:'nav-icon','aria-hidden':'true'},symbol),node('span',{},title)],()=>navigate(key),state.tab===key?'active':'',{'aria-current':state.tab===key?'page':'false','aria-label':title})));
}
async function refresh({quiet=false}={}){
  const generation=++state.request,viewRevision=state.liveRevision;++inspectGeneration;$('refresh').disabled=true;$('content').setAttribute('aria-busy','true');
  if(!quiet)$('content').replaceChildren(node('div',{class:'skeleton','aria-label':'正在加载工作台'}));
  try{
    const [health,projects]=await Promise.all([api('/api/health'),api('/api/projects')]);if(generation!==state.request)return;
    $('health').textContent=`服务正常 · v${health.version}`;state.projects=projects;
    if(!projects.some(p=>p.id===state.project))state.project=projects[0]?.id||'';
    $('project').replaceChildren(...projects.map(p=>node('option',{value:p.id},p.name)));$('project').value=state.project;updateShell();
    if(!state.project){$('content').replaceChildren(empty('注册第一个项目，即可建立代码索引、分析需求并连接实际 Agent。'));$('metrics').replaceChildren();$('export').disabled=true;stopLive();return;}
    $('export').disabled=false;
    const [rules,tasks,workspaces,sessions]=await Promise.all([Promise.all(['active','draft','revoked','deprecated'].map(status=>api(projectPath('rules')+'?status='+status))).then(v=>v.flat()),api(projectPath('tasks')),api(projectPath('worktrees')),api(projectPath('sessions'))]);
    if(generation!==state.request)return;state.rules=rules;state.tasks=tasks;state.workspaces=workspaces;state.sessions=sessions;
    const metrics=[['项目活跃规则',rules.filter(r=>r.status==='active').length],['待审规则候选',rules.filter(r=>r.status==='draft').length],['项目规则实际下发',rules.reduce((a,r)=>a+(r.hit_count||0),0)],['最近在线工作区',workspaces.filter(w=>w.is_online).length]];
    $('metrics').replaceChildren(...metrics.map(([label,value])=>node('div',{class:'metric'},node('span',{},label),node('strong',{},value))));
    const content=node('div');const render={explorer:explorerView,rules:rulesView,tasks:tasksView,analysis:analysisView,context:contextView,workspaces:workspaceView,review:reviewView,debug:debugView,activity:activityView}[state.tab];
    await render(content);if(generation===state.request){const previousScroll=window.scrollY;$('content').replaceChildren(content);if(quiet)window.scrollTo(0,previousScroll);if(viewRevision===state.liveRevision){state.dirty=false;$('live-update').hidden=true;}else scheduleLiveRefresh();}
    if(generation===state.request)ensureLive();
  }catch(error){if(generation===state.request){showError(error);$('content').replaceChildren(errorPanel(error,refresh));}}
  finally{if(generation===state.request){$('refresh').disabled=false;$('content').setAttribute('aria-busy','false');}}
}
function stopLive(){state.liveController?.abort();state.liveController=null;state.liveProject='';clearTimeout(state.liveTimer);$('live-status').textContent='实时流等待连接';}
function scheduleLiveRefresh(){state.dirty=true;$('live-update').hidden=false;clearTimeout(state.liveTimer);state.liveTimer=setTimeout(()=>{const editing=$('editor').open||$('detail').open||$('palette').open||['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName);if(!editing&&state.dirty)refresh({quiet:true});},900);}
function ensureLive(){
  if(state.liveProject===state.project&&state.liveController&&!state.liveController.signal.aborted)return;
  stopLive();const controller=new AbortController(),project=state.project;state.liveController=controller;state.liveProject=project;
  streamEvents(project,controller.signal).catch(error=>{if(error.name!=='AbortError'&&state.project===project)$('live-status').textContent='实时流中断：'+error.message;});
}
async function streamEvents(project,signal){
  const cursorKey='codeneuro:event:'+location.origin+':'+project;let cursor='';try{cursor=sessionStorage.getItem(cursorKey)||'';}catch{/* browser storage may be disabled */}
  let retry=1500;
  while(!signal.aborted){
    try{
      $('live-status').textContent=cursor?'实时流正在续接…':'正在连接实时流…';
      const headers={Accept:'text/event-stream',...(apiToken?{Authorization:'Bearer '+apiToken}:{}),...(cursor?{'Last-Event-ID':cursor}:{})};
      const response=await fetch(`/api/projects/${id(project)}/events`,{headers,signal});if(!response.ok)throw new Error('HTTP '+response.status);if(!response.body)throw new Error('浏览器不支持事件流');
      $('live-status').textContent='● 实时流已连接';retry=1500;
      const reader=response.body.getReader(),decoder=new TextDecoder();let buffer='';
      try{while(!signal.aborted){const {done,value}=await reader.read();if(done)break;buffer+=decoder.decode(value,{stream:true});buffer=buffer.replace(/\r\n/g,'\n');let end;
        while((end=buffer.indexOf('\n\n'))!==-1){const block=buffer.slice(0,end);buffer=buffer.slice(end+2);const event={id:'',data:[]};for(const line of block.split('\n')){if(line.startsWith('id:'))event.id=line.slice(3).trim();else if(line.startsWith('data:'))event.data.push(line.slice(5).trimStart());}
          if(!event.data.length)continue;let data;try{data=JSON.parse(event.data.join('\n'));}catch{continue;}
          const eventId=event.id||String(data.id||'');if(eventId&&cursor&&/^\d+$/.test(eventId)&&/^\d+$/.test(cursor)&&BigInt(eventId)<=BigInt(cursor))continue;
          if(eventId){cursor=eventId;try{sessionStorage.setItem(cursorKey,cursor);}catch{/* storage optional */}}
          if(state.project===project){state.liveRevision++;scheduleLiveRefresh();}
        }
      }}finally{reader.releaseLock();}
      if(!signal.aborted)throw new Error('连接已结束');
    }catch(error){if(signal.aborted)return;$('live-status').textContent=`实时流未连接 · ${error.message} · 正在重试`;}
    await new Promise(resolve=>{const timer=setTimeout(done,retry);function done(){clearTimeout(timer);signal.removeEventListener('abort',done);resolve();}signal.addEventListener('abort',done,{once:true});});retry=Math.min(retry*2,30000);
  }
}
let paletteItems=[],paletteIndex=0;
function commandList(){return [
  ...Object.entries(tabs).map(([key,[label,,symbol]])=>({label,kind:'导航',icon:symbol,run:()=>navigate(key)})),
  {label:'新建任务',kind:'操作',icon:'＋',run:createTask},{label:'新建规则',kind:'操作',icon:'＋',run:()=>ruleForm(null)},{label:'导出静态规则',kind:'操作',icon:'↗',run:exportForm},{label:'刷新当前视图',kind:'操作',icon:'↻',run:refresh},
  ...state.tasks.map(t=>({label:t.title,kind:'需求 · '+(taskLabels[t.status]||t.status),icon:'▥',run:async()=>{state.task=t.id;await navigate('tasks');setTimeout(()=>$('content').querySelector(`[data-task-id="${CSS.escape(t.id)}"]`)?.scrollIntoView({block:'center'}),0);}})),
  ...state.rules.map(r=>({label:r.title,kind:'规则 · '+r.priority+' · v'+r.version,icon:'≋',run:async()=>{state.ruleTerm=r.title;state.ruleFilter='all';await navigate('rules');}})),
  ...state.files.map(path=>({label:path,kind:'文件',icon:'·',run:async()=>{state.path=path;await navigate('explorer');}}))
];}
function drawPalette(){const term=$('palette-input').value.trim().toLowerCase();paletteItems=commandList().filter(c=>(c.label+' '+c.kind).toLowerCase().includes(term)).slice(0,80);paletteIndex=Math.min(paletteIndex,Math.max(0,paletteItems.length-1));$('palette-results').replaceChildren(...paletteItems.map((item,i)=>button([node('span',{'aria-hidden':'true'},item.icon),node('span',{},item.label),node('small',{},item.kind)],()=>runCommand(i),'command'+(i===paletteIndex?' selected':''),{role:'option','aria-selected':i===paletteIndex?'true':'false',onmousemove:()=>{paletteIndex=i;highlightCommand();}})));if(!paletteItems.length)$('palette-results').append(empty('没有匹配的页面、任务、规则或已载入文件。',true));}
function highlightCommand(){Array.from($('palette-results').querySelectorAll('.command')).forEach((b,i)=>{b.classList.toggle('selected',i===paletteIndex);b.setAttribute('aria-selected',String(i===paletteIndex));});$('palette-results').querySelector('.selected')?.scrollIntoView({block:'nearest'});}
async function runCommand(index){const item=paletteItems[index];if(!item)return;$('palette').close();await item.run();}
function openPalette(){paletteIndex=0;$('palette-input').value='';drawPalette();if(!$('palette').open)$('palette').showModal();$('palette-input').focus();}
$('palette-input').oninput=()=>{paletteIndex=0;drawPalette();};$('palette-input').onkeydown=e=>{if(['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();paletteIndex=(paletteIndex+(e.key==='ArrowDown'?1:-1)+paletteItems.length)%Math.max(1,paletteItems.length);highlightCommand();}if(e.key==='Enter'){e.preventDefault();runCommand(paletteIndex).catch(showError);}};
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();if($('palette').open)$('palette').close();else openPalette();}if(e.altKey&&e.key>='1'&&e.key<='9'&&!$('editor').open){e.preventDefault();navigate(Object.keys(tabs)[Number(e.key)-1]).catch(showError);}});
$('project').onchange=e=>{state.project=e.target.value;state.path='';state.task='';state.worktree='';state.job='';state.files=[];state.openDirs.clear();state.ruleTerm='';activityAfter=0;stopLive();refresh();};
$('new-project').onclick=()=>form('注册项目',[{key:'name',label:'项目名称'},{key:'roots',label:'Hub 本机仓库根目录 · 每行一个绝对路径',multiline:true,required:false,help:'远程项目可留空，随后由客户端注册实际工作区。'},{key:'description',label:'说明',required:false}],d=>send('/api/projects','POST',{name:d.name,root_paths:lines(d.roots),description:d.description}).then(p=>{state.project=p.id;state.path='';state.task='';}));
$('refresh').onclick=()=>refresh();$('export').onclick=exportForm;$('open-palette').onclick=openPalette;$('live-update').onclick=()=>refresh({quiet:true});
$('close-editor').onclick=$('cancel-editor').onclick=()=>$('editor').close();$('close-detail').onclick=()=>$('detail').close();
$('detail').addEventListener('close',()=>{if($('detail').dataset.sensitive){$('detail-content').replaceChildren();delete $('detail').dataset.sensitive;}});
for(const dialog of [$('editor'),$('detail'),$('palette')])dialog.addEventListener('close',()=>{if(state.dirty)scheduleLiveRefresh();});
const freshnessTimer=setInterval(()=>{if(!document.hidden&&state.tab==='workspaces'&&!$('editor').open&&!$('detail').open&&!$('palette').open&&$('content').getAttribute('aria-busy')!=='true')refresh({quiet:true});},30000);
window.addEventListener('beforeunload',()=>{stopLive();clearInterval(freshnessTimer);});window.addEventListener('hashchange',()=>{const tab=location.hash.slice(1);if(tabs[tab]&&tab!==state.tab){state.tab=tab;refresh();}});
if(tabs[location.hash.slice(1)])state.tab=location.hash.slice(1);
refresh();

'use strict';
const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const filePath = name => encodeURIComponent(name).replace(/'/g,'%27');
const token = document.querySelector('meta[name="studio-token"]')?.content;
const terminal = new Set(['completed','failed','cancelled','interrupted']);
const statuses = {running:'正在处理',completed:'已完成',failed:'执行失败',cancelled:'已停止',interrupted:'执行中断'};
const state = {workspaces:[],runs:[],models:[],verified:{},settings:{},workspace:null,active:null,engine:'auto',model:null,effort:null,attachments:[],loading:true};
const mark = '<span class="brand-mark"><svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M6 23V11l10-6 10 6v12l-10 6-10-6Z"/><path d="m6 11 10 6 10-6M16 17v12M11 14l10-6"/></svg></span>';
let pollTimer,toastTimer,drawerFocus,settingsTab='models';
async function api(path,body){
  const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Studio-Token':token},body:JSON.stringify(body)});
  const data=await response.json();if(!response.ok)throw Error(data.error || '本机服务返回错误');return data;
}
function activeRun(){return state.runs.find(r=>r.id===state.active);}
function currentSpace(){return state.workspaces.find(w=>w.id===state.workspace);}
function currentModel(){return state.model || state.settings[state.engine==='auto'?'coordinatorModel':'executorModel'];}
function currentEffort(){return state.effort || state.settings[state.engine==='auto'?'coordinatorEffort':'executorEffort'] || 'low';}
function isRunning(){return state.runs.some(r=>!terminal.has(r.status));}
async function refresh(){
  try{const data=await api('/api/bootstrap');Object.assign(state,data);state.workspace=state.workspaces.some(w=>w.id===state.workspace)?state.workspace:state.workspaces[0]?.id;state.loading=false;render();schedulePoll();}
  catch(error){state.loading=false;$('thread').innerHTML='<p class="error-note">'+esc(error.message)+'。请确认本机服务正在运行。</p>';}
}
function acceptRun(run){const i=state.runs.findIndex(r=>r.id===run.id);if(i<0)state.runs.unshift(run);else state.runs[i]=run;}
function schedulePoll(){clearTimeout(pollTimer);if(!isRunning())return;pollTimer=setTimeout(poll,900);}
async function poll(){
  try{for(const run of state.runs.filter(r=>!terminal.has(r.status)))acceptRun(await api('/api/run?id='+encodeURIComponent(run.id)));render();}
  catch(error){toast('连接中断，恢复后会读取后台实际状态');}
  finally{schedulePoll();}
}
function toggleTheme(){document.documentElement.dataset.theme=document.documentElement.dataset.theme==='dark'?'':'dark';try{localStorage.setItem('studio-theme',document.documentElement.dataset.theme);}catch{}}
try{document.documentElement.dataset.theme=localStorage.getItem('studio-theme')||'';}catch{}
const small=matchMedia('(max-width:860px)');
function syncNav(){const sb=$('sidebar');sb.classList.toggle('collapsed',small.matches);sb.inert=small.matches;$('expandBtn').style.display=small.matches?'flex':'none';}
function toggleSidebar(){const closed=$('sidebar').classList.toggle('collapsed');$('sidebar').inert=closed;$('expandBtn').style.display=closed?'flex':'none';}
function closeMobileNav(){if(small.matches&&!$('sidebar').classList.contains('collapsed'))toggleSidebar();}
small.addEventListener('change',syncNav);$('collapseBtn').onclick=toggleSidebar;syncNav();
function closePops(){document.querySelectorAll('.pop').forEach(el=>el.classList.remove('open'));document.querySelectorAll('.chip').forEach(el=>el.setAttribute('aria-expanded','false'));}
function togglePop(id,event){event.stopPropagation();const opened=$(id).classList.contains('open');closePops();if(opened)return;id==='execPop'?renderExec():renderModels();$(id).classList.add('open');$(id==='execPop'?'execChip':'modelChip').setAttribute('aria-expanded','true');$(id).querySelector('button:not(:disabled)')?.focus();}
function renderExec(){
  $('execPop').innerHTML='<div class="pop-head">执行方式 · 本次覆盖</div>'+[['auto','自动','由主控直接回答或安排文件执行'],['codex','Codex','跳过主控分流，直接使用 Codex 文件执行器'],['claude','Claude Code','尚未接入任务适配器'],['workbuddy','WorkBuddy','桌面调用接口与额度尚未验证']].map(([id,name,description])=>`<button class="opt" ${!['auto','codex'].includes(id)?'disabled':''} onclick="pickExec('${id}')"><span class="opt-main"><span class="opt-name">${name} ${state.engine===id?'✓':''}</span><span class="opt-sub">${description}</span></span></button>`).join('')+'<div class="opt-sep"></div><button class="opt" onclick="openSettings()">执行器与连接设置 →</button>';
}
function renderModels(){
  const candidates=state.models.filter(m=>state.verified[m.id]);
  $('modelPop').innerHTML=`<div class="pop-head">${state.engine==='auto'?'主控型号':'执行型号'} · 本次覆盖</div>`+candidates.map(m=>`<button class="opt" onclick="pickModel('${m.id}')"><span class="opt-main"><span class="opt-name">${esc(m.name)} ${currentModel()===m.id?'✓':''}</span><span class="opt-sub">${esc(m.id)} · 已完成真实连接测试</span></span></button>`).join('')+(candidates.length?'':'<p class="help-block">先在设置中测试一个具体型号，成功后才能选择。</p>')+'<div class="opt-sep"></div><button class="opt" onclick="openSettings()">发现与验证其他模型 →</button>';
}
function pickExec(engine){state.engine=engine;state.model=null;state.effort=null;closePops();updateHint();if(isRunning())toast('仅作用于下一次请求，当前运行不变');}
function pickModel(model){state.model=model;const meta=state.models.find(m=>m.id===model);state.effort=meta?.defaultEffort||'low';closePops();updateHint();if(isRunning())toast('型号变更仅在下一次请求生效');}
function updateHint(){
  const engine=state.engine==='auto'?'自动':'Codex';$('execVal').textContent=engine;$('execChip').setAttribute('aria-label','执行方式 '+engine);
  $('modelVal').textContent=currentModel()||'未配置';$('modelChip').setAttribute('aria-label','模型 '+(currentModel()||'未配置'));
  $('hintRight').textContent=(state.engine==='auto'?'主控':'执行器')+'：'+(currentModel()||'请先设置具体型号')+' · '+currentEffort();syncSend();
}
function autoGrow(el){el.style.height='auto';el.style.height=Math.min(el.scrollHeight,160)+'px';}
function syncSend(){const busy=isRunning();$('sendBtn').disabled=state.loading || (!busy&&!$('ta').value.trim());$('sendBtn').classList.toggle('stop',busy);$('sendBtn').setAttribute('aria-label',busy?'停止运行':'发送');$('sendBtn').title=busy?'停止运行':'发送';$('sendIco').innerHTML=busy?'<rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor" stroke="none"/>':'<path d="M12 19V5"/><path d="m5 12 7-7 7 7"/>';}
function onKey(event){if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();if(!isRunning())sendOrStop();}}
async function sendOrStop(){
  if(isRunning()){const run=state.runs.find(r=>!terminal.has(r.status));$('sendBtn').disabled=true;try{acceptRun(await api('/api/cancel',{id:run.id}));render();}catch(error){toast(error.message);syncSend();}return;}
  const text=$('ta').value.trim();if(!text)return;
  if(!currentModel()){openSettings();return;}
  try{
    $('sendBtn').disabled=true;
    const run=await api('/api/runs',{workspace:state.workspace,text,engine:state.engine,model:currentModel(),effort:currentEffort(),allowWrite:$('allowWrite').checked,parent:state.active});
    acceptRun(run);state.active=run.id;$('ta').value='';autoGrow($('ta'));$('allowWrite').checked=false;state.attachments=[];renderAttachments();render();schedulePoll();
  }catch(error){toast(error.message);syncSend();}
}
function newTask(){state.active=null;$('ta').value='';$('allowWrite').checked=false;state.attachments=[];renderAttachments();closeDrawer();closeMobileNav();render();$('ta').focus();}
function fillTask(text){$('ta').value=text;autoGrow($('ta'));syncSend();$('ta').focus();}
function openTask(id){state.active=id;const run=activeRun();if(run)state.workspace=run.workspace;closeDrawer();closeMobileNav();render();}
function renderSidebar(){document.querySelector('.sb-ws-name').textContent=currentSpace()?.name||'工作空间';const runs=state.runs.filter(r=>r.workspace===state.workspace);
  document.querySelector('.sb-scroll').innerHTML='<div class="sb-label">最近对话</div>'+runs.slice(0,40).map(r=>`<button class="sb-item ${r.id===state.active?'active':''}" style="width:100%;text-align:left" onclick="openTask('${r.id}')"><span class="sb-dot ${r.status==='running'?'pulse':''}"></span><span class="t">${esc(r.text.slice(0,26))}</span></button>`).join('')+(runs.length?'':'<p class="help-block" style="padding:8px 20px">对话和文件记录保存在本机。</p>');}
function turn(who,body){return `<div class="turn ${who==='你'?'me':''}"><div class="turn-av ${who==='你'?'me':'coord'}">${who==='你'?'h':'A'}</div><div class="turn-body"><div class="turn-head"><span class="turn-name">${who}</span></div>${body}</div></div>`;}
function chain(){let run=activeRun();const result=[];while(run&&result.length<12){result.unshift(run);run=state.runs.find(r=>r.id===run.parent);}return result;}
function renderRun(run){
  let answer=run.answer?`<div class="answer-body">${esc(run.answer)}</div>`:'';
  if(run.status==='running')answer+=`<div class="status-note">${run.phase==='coordinator'?'主控正在思考…':'Codex 正在处理文件任务…'}</div>`;
  if(run.error)answer+=`<div class="error-note">${esc(run.error)}</div>`;
  const files=run.files||[];
  if(files.length)answer+='<div class="file-evidence">'+files.map(f=>`<button onclick="showFile('${esc(filePath(f.path))}','${run.workspace}')">${f.action==='read'?'已读取':'已创建'} · ${esc(f.path)}</button>`).join('')+'</div>';
  const models=[...new Set((run.calls||[]).map(c=>c.requestedModel))];
  answer+=`<div class="answer-meta"><span>${esc(models.join(' → ')||run.requestedModel)}</span><span>${esc(statuses[run.status]||run.status)}</span><button onclick="openDrawer('${run.id}')">${run.kind==='chat'?'用量与来源':'任务详情'} →</button></div>`;
  return turn('你','<div class="answer-body">'+esc(run.text)+'</div>')+turn('协调器',answer);
}
function render(){
  const followEnd=$('scroll').scrollHeight-$('scroll').scrollTop-$('scroll').clientHeight<80;
  renderSidebar();const run=activeRun();$('taskTitle').textContent=run?run.text.slice(0,24):(currentSpace()?.name||'工作空间');$('taskSub').textContent=run?statuses[run.status]:'本机运行';
  if(!run){$('thread').innerHTML=`<section class="empty"><div class="empty-inner"><div class="empty-mark">${mark}</div><h1 class="empty-title">今天要完成什么？</h1><p class="empty-sub">把目标说清楚，剩下的交给协调器。<br>直接问答，或在当前工作空间中完成文件任务。</p><div class="suggestions"><button class="suggestion" onclick="fillTask('你是谁？')">开始对话 ↗</button><button class="suggestion" onclick="fillTask('列出当前工作空间的文本文件，读取其中一份并摘要两句。')">整理一份资料 ↗</button><button class="suggestion" onclick="fillTask('创建一份 project-note.md，说明这个工作空间的目标与验收方式。')">生成项目说明 ↗</button></div><div class="sample-intro"><small>${currentModel()?'主控：'+esc(currentModel())+' · 已验证连接':'首次使用，请先选择并测试主控型号'}</small><button onclick="openSettings()"><span>主控、执行器与模型</span><span style="color:var(--text-3)">设置 →</span></button><p class="muted">只读为默认。创建文件需在输入框下方授权本次操作。</p></div></div></section>`;}
  else $('thread').innerHTML=chain().map(renderRun).join('');
  updateHint();if(followEnd)$('scroll').scrollTop=$('scroll').scrollHeight;if($('drawer').classList.contains('open')&&document.querySelector('.drawer-title').textContent==='任务详情')renderDetails();
}
function openDrawer(id){if(id)state.detailId=id;else state.detailId=state.active;drawerFocus=document.activeElement;renderDetails();$('drawer').classList.add('open');$('drawer').inert=false;$('drawer').setAttribute('aria-hidden','false');requestAnimationFrame(()=>$('drawer').querySelector('button').focus());}
function closeDrawer(){$('drawer').classList.remove('open');$('drawer').inert=true;$('drawer').setAttribute('aria-hidden','true');drawerFocus?.focus?.();}
function toggleDrawer(){$('drawer').classList.contains('open')?closeDrawer():openDrawer();}
function renderDetails(){
  document.querySelector('.drawer-title').textContent='任务详情';const run=state.runs.find(r=>r.id===(state.detailId||state.active));if(!run){$('drawerBody').innerHTML='<p class="muted">发起对话后，可查看模型来源、用量和真实文件操作。</p>';return;}
  const calls=run.calls||[];
  $('drawerBody').innerHTML=`<div class="drawer-sec"><h4>这次做了什么</h4><p>${esc(run.text)}</p><p class="muted">${statuses[run.status]} · ${run.route==='answer'?'主控直接回答':run.route==='manual'?'用户指定 Codex':'主控安排文件任务'}</p></div><div class="drawer-sec"><h4>执行与权限</h4><dl class="kv"><dt>工作空间</dt><dd>${esc(state.workspaces.find(w=>w.id===run.workspace)?.name)}</dd><dt>请求型号</dt><dd>${esc(run.requestedModel)}</dd><dt>上游实际型号</dt><dd>CLI 未回传，不能独立核对</dd><dt>推理强度</dt><dd>${esc(run.effort)}</dd><dt>文件权限</dt><dd>${run.allowWrite?'本次允许新建文本文件':'只读'}，不允许覆盖/删除/命令</dd><dt>独立审核</dt><dd>尚未接入，未执行</dd><dt>开始时间</dt><dd>${esc(run.created)}</dd><dt>结束时间</dt><dd>${esc(run.ended||'—')}</dd></dl></div><div class="drawer-sec"><h4>调用与真实用量</h4>${calls.map(c=>`<div class="connection"><strong>${c.role==='coordinator'?'主控':'执行器'} · ${esc(c.requestedModel)}</strong><p>会话：${esc(c.sessionId)}<br>输入 ${c.usage?.input_tokens??'未知'} · 输出 ${c.usage?.output_tokens??'未知'} · 缓存 ${c.usage?.cached_input_tokens??'未知'}<br>来源：Codex CLI turn.completed；费用未知，未返回实际扣费。</p></div>`).join('')||'<p class="muted">运行完成后记录本次调用；失败不表示没有消耗额度。</p>'}</div><div class="drawer-sec"><h4>资料与产物</h4>${(run.files||[]).map(f=>`<button class="filerow" style="width:100%;text-align:left" onclick="showFile('${esc(filePath(f.path))}','${run.workspace}')">${f.action==='read'?'读取':'创建'} ${esc(f.path)} · ${f.bytes} 字节 →</button>`).join('')||'<p class="muted">无已核对文件操作。</p>'}</div><details class="drawer-sec"><summary>查看技术事件</summary><div class="log">${run.events.map(e=>`<div>${esc(e.type)} ${esc(e.role||'')} ${esc(e.tool||'')} ${esc(e.requestedModel||'')} ${esc(e.message||'')}</div>`).join('')}</div></details><p class="muted">取消不会自动撤销已创建文件。有副作用的任务不会自动重试。</p>`;
}
async function showFile(encoded,workspace){
  try{const file=await api('/api/file?workspace='+encodeURIComponent(workspace)+'&name='+encoded);openDrawer();document.querySelector('.drawer-title').textContent=file.name;$('drawerBody').innerHTML='<p class="muted" style="margin-bottom:14px">来自本机当前工作空间的真实文本文件</p><article class="preview-text">'+esc(file.text)+'</article>';}
  catch(error){toast(error.message);}
}
function modal(title,body){closeDrawer();closePops();closeMobileNav();$('modalBody').innerHTML=`<div class="modal-head"><h2>${title}</h2><button class="iconbtn" aria-label="关闭窗口" onclick="document.getElementById('modal').close()">×</button></div>${body}`;if(!$('modal').open)$('modal').showModal();}
function workspaceDialog(){modal('工作空间',state.workspaces.map(w=>`<button class="opt" style="width:100%;text-align:left" onclick="switchWorkspace('${w.id}')">${esc(w.name)} ${w.id===state.workspace?'✓':''}</button>`).join('')+'<div class="new-space"><input id="spaceName" aria-label="新工作空间名称" placeholder="新工作空间名称" maxlength="40"><button class="btn btn-ghost" onclick="createSpace()">创建</button></div><p class="help-block">工作空间独立存储。此阶段仅访问应用内部目录，外部业务目录未授权。</p>');}
function switchWorkspace(id){state.workspace=id;$('modal').close();newTask();}
async function createSpace(){try{const w=await api('/api/workspaces',{name:$('spaceName').value});state.workspaces.push(w);switchWorkspace(w.id);}catch(e){toast(e.message);}}
function openSettings(tab='models'){settingsTab=typeof tab==='string'?tab:'models';renderSettings();}
function renderSettings(){
  const tabs=[['models','模型与连接'],['defaults','主控与默认执行'],['safety','权限与预算'],['general','通用']];
  let content='';
  if(settingsTab==='models')content='<p class="muted">来自本机 Codex App Server 的候选目录。测试会发起一次真实请求并消耗额度；成功后才可选择，不保证未来始终有权限。</p>'+state.models.map(m=>`<div class="model-test-row"><div><strong>${esc(m.name)}</strong><small>${esc(m.id)} · ${state.verified[m.id]?'真实请求已完成':'尚未测试'}</small></div><button class="btn btn-ghost btn-sm" onclick="verifyModel('${m.id}',this)">${state.verified[m.id]?'重新测试':'测试连接'}</button></div>`).join('')+'<p class="help-block">Claude Code：已安装但未接入。WorkBuddy：桌面接口尚未验证。不会偷偷换用其他执行器。</p><button class="btn btn-ghost" onclick="discover(this)">重新获取模型目录</button>';
  if(settingsTab==='defaults')content='<p class="muted">主控负责对话与安排；执行器负责文件任务。这里只能选择通过真实请求测试的型号。</p>'+roleConfig('coordinator','主控型号')+roleConfig('executor','Codex 默认执行型号')+'<p class="help-block">独立审核尚未接入，因此没有虚假的审核模型开关。输入框的型号选择仅覆盖本次请求。</p><button class="btn btn-primary" onclick="saveDefaults(this)">保存模型配置</button>';
  if(settingsTab==='safety')content=`<p class="muted">权限由后端强制执行，模型不能扩大范围。</p><div class="setting-row"><label for="maxCalls">单次请求最多模型调用次数</label><select id="maxCalls"><option value="1" ${state.settings.maxCalls===1?'selected':''}>1 次（主控直接回答 / 手动执行）</option><option value="2" ${state.settings.maxCalls!==1?'selected':''}>2 次（允许主控安排一个执行器）</option></select></div><p class="help-block">默认只读；仅本次授权后可创建 md/txt，不允许覆盖、删除、Shell、生产发布或跨工作空间访问。<br>当前无法获得实际金额，不能承诺按金额硬限额；Token 来自 CLI，费用显示未知。<br>连接测试会另行消耗一次调用，不计入任务上限。</p><button class="btn btn-primary" onclick="saveBudget()">保存调用上限</button>`;
  if(settingsTab==='general')content='<div class="setting-row"><label>界面</label><button class="btn btn-ghost" onclick="toggleTheme()">切换浅色 / 深色</button></div><p class="help-block">语言：简体中文<br>存储：项目本机 .studio/，不上传 GitHub。<br>运行记录：SQLite；网页刷新会读取后台状态。<br>服务重启后未完成任务标记中断，不自动重复执行。</p>';
  modal('设置',`<nav class="settings-tabs">${tabs.map(([id,label])=>`<button class="${id===settingsTab?'active':''}" onclick="openSettings('${id}')">${label}</button>`).join('')}</nav>${content}`);
}
function roleConfig(role,label){const selected=state.settings[role+'Model'];const models=state.models.filter(m=>state.verified[m.id]);const effort=state.settings[role+'Effort']||'low';return `<div class="setting-row"><label for="${role}Model">${label}</label><select id="${role}Model" onchange="syncEffort('${role}')"><option value="">请选择已验证型号</option>${models.map(m=>`<option value="${esc(m.id)}" ${m.id===selected?'selected':''}>${esc(m.id)}</option>`).join('')}</select><label for="${role}Effort" style="margin-top:10px">推理强度</label><select id="${role}Effort">${(state.models.find(m=>m.id===selected)?.efforts||['low']).map(e=>`<option ${e===effort?'selected':''}>${e}</option>`).join('')}</select></div>`;}
function syncEffort(role){const model=state.models.find(m=>m.id===$(role+'Model').value);$(role+'Effort').innerHTML=(model?.efforts||['low']).map(e=>`<option>${esc(e)}</option>`).join('');}
async function verifyModel(id,button){
  button.disabled=true;button.textContent='正在真实测试…';
  try{const model=state.models.find(m=>m.id===id);state.verified[id]=await api('/api/verify',{model:id,effort:model.defaultEffort});renderSettings();toast('连接测试已完成，可在主控与默认执行中选择');}
  catch(error){button.disabled=false;button.textContent='重试连接';toast(error.message);}
}
async function discover(button){button.disabled=true;try{const boot=await api('/api/discover',{});state.models=boot.models;renderSettings();}catch(e){toast(e.message);button.disabled=false;}}
async function saveDefaults(button){button.disabled=true;try{state.settings=await api('/api/settings',{...state.settings,coordinatorModel:$('coordinatorModel').value,coordinatorEffort:$('coordinatorEffort').value,executorModel:$('executorModel').value,executorEffort:$('executorEffort').value});state.model=null;state.effort=null;updateHint();renderSettings();toast('已保存，下次请求生效');}catch(e){toast(e.message);button.disabled=false;}}
async function saveBudget(){try{state.settings=await api('/api/settings',{...state.settings,maxCalls:Number($('maxCalls').value)});toast('调用上限已保存');}catch(e){toast(e.message);}}
function openStrategy(){openSettings('safety');}
async function knowledge(){try{const files=await api('/api/files?workspace='+state.workspace);modal('项目知识',`<p class="muted">当前空间：${esc(currentSpace()?.name)}。支持 UTF-8 md/txt，每份最多 256KB。添加后保存在本机；模型读取时会记录来源。</p>${files.map(f=>`<button class="filerow" style="width:100%;text-align:left" onclick="document.getElementById('modal').close();showFile('${esc(filePath(f.path))}','${state.workspace}')">${esc(f.path)} · ${f.bytes} 字节 →</button>`).join('')||'<p class="help-block">尚未添加资料。</p>'}<button class="btn btn-ghost" style="margin-top:16px" onclick="attachment()">添加文本文件</button><p class="help-block">PDF/DOCX、外部目录绑定、删除与索引管理尚未开放。</p>`);}catch(e){toast(e.message);}}
function attachment(){
  const input=document.createElement('input');input.type='file';input.accept='.md,.txt';input.multiple=true;
  input.onchange=async()=>{for(const file of input.files){try{if(file.size>256*1024)throw Error('附件超过 256KB');if(!/\.(md|txt)$/i.test(file.name))throw Error('仅支持 md/txt 文本');const text=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());await api('/api/upload',{workspace:state.workspace,name:file.name,text});state.attachments.push(file.name);renderAttachments();toast('已保存到当前工作空间，可在任务中引用文件名');}catch(e){toast(file.name+'：'+e.message);}}};input.click();
}
function renderAttachments(){let node=$('attachments');if(!node){node=document.createElement('div');node.id='attachments';node.className='attach-list';document.querySelector('.composer-field').after(node);}node.innerHTML=state.attachments.map(name=>`<span class="file-chip">已保存 · ${esc(name)}</span>`).join('');}
function toast(message){let node=$('toast');if(!node){node=document.createElement('div');node.id='toast';node.setAttribute('role','status');node.style.cssText='position:fixed;left:50%;bottom:100px;transform:translateX(-50%);background:var(--text);color:var(--surface);font-size:12px;padding:10px 16px;border-radius:8px;z-index:300;max-width:85vw';document.body.append(node);}node.textContent=message;node.hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>node.hidden=true,4500);}
document.addEventListener('click',e=>{if(!e.target.closest('.pop,.chip'))closePops();});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){closePops();closeDrawer();closeMobileNav();}if((e.key==='Enter'||e.key===' ')&&e.target.matches('[role=button]')){e.preventDefault();e.target.click();}});
$('drawer').addEventListener('keydown',e=>{if(e.key!=='Tab')return;const f=[...$('drawer').querySelectorAll('button:not(:disabled),a,input')];if(e.shiftKey&&document.activeElement===f[0]){e.preventDefault();f.at(-1).focus();}else if(!e.shiftKey&&document.activeElement===f.at(-1)){e.preventDefault();f[0].focus();}});
$('modal').addEventListener('click',e=>{if(e.target===$('modal')){const r=$('modal').getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$('modal').close();}});
document.querySelector('[aria-label="添加附件"]').onclick=attachment;
for(const item of document.querySelectorAll('.sb-foot .sb-item')){item.role='button';item.tabIndex=0;if(item.textContent.includes('项目知识'))item.onclick=knowledge;if(item.textContent.trim()==='设置')item.onclick=()=>openSettings('defaults');}
const permission=document.createElement('label');permission.className='write-permission';permission.innerHTML='<input id="allowWrite" type="checkbox"> 本次允许在当前工作空间新建文本文件（不覆盖已有文件）';document.querySelector('.composer').append(permission);
$('drawer').inert=true;refresh();

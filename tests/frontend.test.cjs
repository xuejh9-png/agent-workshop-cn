// Exercise the actual standalone functions from the vanilla browser script.
// No DOM implementation or copied business logic is substituted for them.
const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const src=fs.readFileSync(require('node:path').join(__dirname,'../app.js'),'utf8');
function fn(name,next){return src.slice(src.indexOf('async function '+name),src.indexOf('\nfunction '+next,src.indexOf('async function '+name)));}
const apiSource=fn('api','rememberView');
const sendSource=src.slice(src.indexOf('async function sendOrStop'),src.indexOf('\nfunction newTask',src.indexOf('async function sendOrStop')));

test('concurrent old-token requests both retry once after a server restart',async()=>{
  const posts=[];
  const c=vm.createContext({token:'old',DOMParser:class{parseFromString(){return {querySelector:()=>({content:'fresh'})};}},fetch:async(url,opt)=>{
    if(url==='/')return {ok:true,text:async()=>'<meta>'};
    const auth=opt.headers['X-Studio-Token'];posts.push({url,auth});
    return auth==='old'?{status:403,ok:false,json:async()=>({error:'stale'})}:{status:200,ok:true,json:async()=>({ok:true})};
  }});
  vm.runInContext(apiSource+';this.api=api;',c);
  assert.deepEqual(await Promise.all([c.api('/a',{x:1}),c.api('/b',{x:2})]),[{ok:true},{ok:true}]);
  assert.equal(posts.length,4);assert.equal(posts.filter(p=>p.auth==='fresh').length,2);
});

function sender(api){
  const input={value:'same text',checked:false},permission={checked:false},button={};
  const state={workspace:'A',conversation:'convA',managerHost:'codex',allowedEmployees:['codex'],conversations:[],runs:[]};
  let serial=0;
  const c=vm.createContext({state,sourceSelection:{projectId:null,files:[]},pendingRequest:null,sending:null,
    $:id=>id==='ta'?input:id==='allowWrite'?permission:button,verified:()=>true,managerProfile:()=>({model:'m'}),currentBusy:()=>null,
    crypto:{randomUUID:()=>String(++serial)},api,acceptRun:r=>state.runs.push(r),syncSend:()=>{},updateHint:()=>{},schedulePoll:()=>{},
    renderMessages:()=>{},autoGrow:()=>{},rememberView:()=>{},renderSidebar:()=>{},toast:()=>{},openSettings:()=>{},loadConversation:async()=>{}});
  vm.runInContext(sendSource+';this.sendOrStop=sendOrStop;',c);return {c,state,input,permission};
}
test('same-text retry in another conversation receives a new context and request ID',async()=>{
  const requests=[];const {c,state}=sender(async(_,body)=>{requests.push({...body});throw Error('offline');});
  await c.sendOrStop();state.workspace='B';state.conversation='convB';state.allowedEmployees=[];
  await c.sendOrStop();assert.equal(requests[1].projectId,'B');assert.equal(requests[1].conversationId,'convB');
  assert.notEqual(requests[1].requestId,requests[0].requestId);assert.deepEqual(Array.from(requests[1].allowedEmployees),[]);
});
test('ambiguous network failure in the same context keeps the same request ID',async()=>{
  const requests=[];const {c}=sender(async(_,body)=>{requests.push({...body});throw Error('offline');});
  await c.sendOrStop();await c.sendOrStop();assert.equal(requests[1].requestId,requests[0].requestId);
});
test('late submission response preserves another project draft and cannot duplicate submission',async()=>{
  let release;const requests=[];const {c,state,input,permission}=sender((_,body)=>{requests.push(body);return new Promise(r=>release=r);});
  const pending=c.sendOrStop();await c.sendOrStop();assert.equal(requests.length,1);
  state.workspace='B';state.conversation=null;input.value='new B draft';permission.checked=true;
  release({id:'r',conversationId:'convA',projectId:'A',text:'same text',created:'now',status:'running'});await pending;
  assert.equal(input.value,'new B draft');assert.equal(permission.checked,true);assert.equal(state.conversation,null);assert.equal(c.sending,null);
});

for(const name of ['reviewSource','cancelSourceReview','applySource','bindSource'])test(name+' does not reopen a dismissed or replaced panel',async()=>{
  let release,refreshes=0;
  const c=vm.createContext({panelRequest:5,sourceView:{id:'r',pid:'A',changes:[{path:'a.py',afterHash:'sha'}]},
    sourceSelection:{},$:()=>({value:'/specific/project'}),api:()=>new Promise(r=>release=r),
    sourceChanges:async()=>refreshes++,sourceDirectory:async()=>refreshes++});
  const line=src.split('\n').find(l=>l.startsWith('async function '+name+'('));assert.ok(line);
  vm.runInContext(line+';this.action='+name+';',c);
  const pending=name==='applySource'?c.action('r','A',0,false):name==='bindSource'?c.action('A'):c.action('r','A');
  c.panelRequest++;release({});await pending;assert.equal(refreshes,0);
});

test('a delayed run response cannot revert a newer terminal state',()=>{
  const c=vm.createContext({state:{runs:[{id:'r',version:9,status:'completed'}]}});
  vm.runInContext(src.split('\n').find(l=>l.startsWith('function acceptRun('))+';this.acceptRun=acceptRun;',c);
  c.acceptRun({id:'r',version:2,status:'running'});assert.equal(c.state.runs[0].status,'completed');
});
test('unread steps from another conversation do not trigger endless polling',()=>{
  const c=vm.createContext({state:{conversation:'B',messages:new Map(),runs:[{id:'r',conversationId:'A',version:1,steps:[{step:1}]}]},settled:new Set()});
  vm.runInContext(src.split('\n').find(l=>l.startsWith('function stepsPending('))+';this.stepsPending=stepsPending;',c);
  assert.equal(c.stepsPending(),false);c.state.conversation='A';assert.equal(c.stepsPending(),true);
});

for(const action of ['chooseSource','clearSource'])test(action+' invalidates an outstanding bind without losing the new selection',async()=>{
  let release,refreshes=0;
  const c=vm.createContext({panelRequest:1,sourceView:null,sourceTimer:null,sourceSelection:{},pendingRequest:null,
    clearTimeout:()=>{},toast:()=>{},document:{querySelectorAll:()=>[{value:'a.py'}]},
    $:id=>id==='sourcePath'?{value:'/project'}:id==='modal'?{close:()=>{}}:{textContent:''},
    api:()=>new Promise(r=>release=r),sourceDirectory:async()=>refreshes++});
  for(const name of ['dismissModal','chooseSource','clearSource','bindSource'])vm.runInContext(src.split('\n').find(l=>l.startsWith('function '+name+'(')||l.startsWith('async function '+name+'(')),c);
  const pending=c.bindSource('A');c[action]('A');release({});await pending;
  assert.equal(refreshes,0);assert.deepEqual(Array.from(c.sourceSelection.files),action==='chooseSource'?['a.py']:[]);
});

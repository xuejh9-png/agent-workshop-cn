"""Versioned settings and additive project/conversation records. Legacy rows stay intact."""
import copy, hashlib, json, uuid
from datetime import datetime

def stamp():return datetime.now().astimezone().isoformat(timespec='microseconds')

def profile(model=None,effort='low'):return {'model':model,'effort':effort}

class Configurations:
    def __init__(self,app):self.app=app
    def get(self):
        value=self.app.store.get('settings','v2')
        if value:return value
        old=self.app.settings()
        value={'schemaVersion':2,'revision':0,'productName':'Agent Studio','managerHost':'codex','managerModelByHost':{'codex':profile(old.get('coordinatorModel'),old.get('coordinatorEffort','low'))},'employeeProfilesByHost':{'codex':{'enabled':True,**profile(old.get('executorModel'),old.get('executorEffort','low'))}},'reviewPolicy':{'enabled':False},'updatedAt':stamp()}
        self.app.store.put('settings','v2',value);return value
    def identity(self):
        return self.app.adapter.account_identity()
    def key(self,host,model,identity):return host+':'+identity['accountId']+':'+identity['configId']+':'+model
    def verified(self):return self.app.store.get('settings','verified_v2',{})
    def check(self,host,p,identity,required=True):
        if host!='codex':raise ValueError('该宿主尚未接入受控调用，不可使用')
        if not isinstance(p,dict):raise ValueError('型号配置格式错误')
        self.app.validate_model(p.get('model'),p.get('effort'),False)
        if required and self.key(host,p['model'],identity) not in self.verified():raise ValueError('此宿主/当前账号/连接配置下的型号未完成真实测试，请先验证')
    def save(self,body):
        with self.app.lock:return self._save(body)
    def _save(self,body):
        if body.get('schemaVersion')!=2:raise ValueError('请刷新到新版设置界面')
        old=self.get()
        if body.get('revision')!=old['revision']:raise ValueError('配置已被其他页面修改，请先重新读取，当前表单未保存')
        candidate=copy.deepcopy(body);identity=self.identity();host=candidate.get('managerHost')
        managers=candidate.get('managerModelByHost');employees=candidate.get('employeeProfilesByHost')
        if not isinstance(managers,dict) or not isinstance(employees,dict):raise ValueError('经理或员工配置缺失')
        if any(h not in ('codex',) for h in set(managers)|set(employees)):raise ValueError('未接通的宿主不能保存为可用配置')
        self.check(host,managers.get(host),identity)
        for h,p in employees.items():
            if not isinstance(p,dict) or type(p.get('enabled')) is not bool:raise ValueError('员工启用状态无效')
            if p['enabled']:self.check(h,p,identity)
            elif p.get('model'):self.check(h,p,identity,False)
        if candidate.get('reviewPolicy',{}).get('enabled'):raise ValueError('独立审核尚未接入，不可启用')
        name=candidate.get('productName','Agent Studio')
        if not isinstance(name,str) or not 1<=len(name.strip())<=60:raise ValueError('产品展示名格式无效')
        clean={'schemaVersion':2,'revision':old['revision']+1,'productName':name.strip(),'managerHost':host,'managerModelByHost':managers,'employeeProfilesByHost':employees,'reviewPolicy':{'enabled':False},'updatedAt':stamp()}
        self.app.store.put('settings','v2',clean)
        return self.get()
    def verify(self,host,model,effort):
        identity=self.identity();self.check(host,profile(model,effort),identity,False)
        result=self.app.verify(model,effort)
        if self.identity()!=identity:raise ValueError('验证期间登录或连接配置变化，请重新验证')
        result={**result,'host':host,'accountId':identity['accountId'],'configId':identity['configId']}
        with self.app.lock:
            verified=self.verified();verified[self.key(host,model,identity)]=result;self.app.store.put('settings','verified_v2',verified)
        return result
    def resolve(self,host,allowed):
        settings=self.get();identity=self.identity()
        if not isinstance(allowed,list) or len(allowed)>3 or len(set(allowed))!=len(allowed):raise ValueError('员工授权必须是无重复的列表')
        self.check(host,settings['managerModelByHost'].get(host),identity)
        snapshots={}
        for employee in allowed:
            p=settings['employeeProfilesByHost'].get(employee)
            if not p or not p.get('enabled'):raise ValueError('员工未启用或尚未接入：'+str(employee))
            self.check(employee,p,identity);snapshots[employee]=copy.deepcopy(p)
        return settings,identity,snapshots

class Projects:
    def __init__(self,app):self.app=app;self.store=app.store;self.migrate()
    def migrate(self):
        pending=[];warnings=[];workspaces={w['id']:w for w in self.store.all('workspace')};runs={r['id']:r for r in self.store.all('run')}
        for w in workspaces.values():
            if not self.store.get('project',w['id']):pending.append(('project',w['id'],{'id':w['id'],'name':w['name'],'created':w['created'],'workspace':w['id']}))
        missing=[r for r in runs.values() if not self.store.get('run_link',r['id'])]
        groups={}
        for run in missing:
            if run.get('workspace') not in workspaces:warnings.append({'runId':run['id'],'reason':'missing_workspace'});continue
            r=run;seen=[]
            while r.get('parent'):
                if r['id'] in seen:
                    r=runs[min(seen)];warnings.append({'runId':run['id'],'reason':'parent_cycle'});break
                seen.append(r['id']);parent=runs.get(r['parent'])
                if not parent or parent.get('workspace')!=run['workspace']:
                    warnings.append({'runId':run['id'],'reason':'missing_or_cross_project_parent'});break
                r=parent
            cid=uuid.uuid5(uuid.NAMESPACE_URL,'studio-legacy:'+run['workspace']+':'+r['id']).hex
            groups.setdefault((cid,run['workspace']),[]).append(run)
        for (cid,pid),items in groups.items():
            items.sort(key=lambda r:(r.get('created',''),r['id']))
            if not self.store.get('conversation',cid):pending.append(('conversation',cid,{'id':cid,'projectId':pid,'title':items[0].get('text','历史记录')[:60],'created':items[0]['created'],'updated':items[-1]['created'],'legacy':True}))
            existing=self.messages(cid);seq=max((m['sequence'] for m in existing),default=0)
            for run in items:
                pending.append(('run_link',run['id'],{'runId':run['id'],'conversationId':cid,'projectId':pid}))
                for role,text in [('user',run.get('text','')),('assistant',run.get('answer',''))]:
                    seq+=1;mid=run['id']+':'+role
                    pending.append(('message',mid,{'id':mid,'conversationId':cid,'projectId':pid,'runId':run['id'],'role':role,'text':text,'sequence':seq,'legacyParent':run.get('parent')}))
        if pending:self.store.put_many(pending)
        previous=self.store.get('migration','v12',{'warnings':[]})
        for warning in warnings:
            if warning not in previous['warnings']:previous['warnings'].append(warning)
        previous.update(version=1,at=stamp());self.store.put('migration','v12',previous)
    def project(self,pid):
        project=self.store.get('project',pid)
        if not project:raise ValueError('项目不存在')
        return project
    def create_project(self,name):
        w=self.app.workspace(name);value={'id':w['id'],'workspace':w['id'],'name':w['name'],'created':w['created']};self.store.put('project',w['id'],value);return value
    def rename_project(self,pid,name):
        p=self.project(pid)
        if not isinstance(name,str) or not 1<=len(name.strip())<=40:raise ValueError('项目名为1–40字')
        p['name']=name.strip();self.store.put('project',pid,p);return p
    def new_conversation(self,pid,title='新对话'):
        self.project(pid)
        if not isinstance(title,str) or not 1<=len(title.strip())<=60:raise ValueError('对话标题为1–60字')
        ident=uuid.uuid4().hex;v={'id':ident,'projectId':pid,'title':title.strip(),'created':stamp(),'updated':stamp(),'legacy':False};self.store.put('conversation',ident,v);return v
    def conversation(self,ident,pid=None):
        value=self.store.get('conversation',ident)
        if not value or (pid and value['projectId']!=pid):raise ValueError('对话不属于当前项目')
        return value
    def messages(self,cid):return sorted([m for m in self.store.all('message') if m['conversationId']==cid],key=lambda m:m['sequence'])
    def page(self,cid,before=None,limit=40):
        conv=self.conversation(cid);allmessages=self.messages(cid)
        if before is not None:allmessages=[m for m in allmessages if m['sequence']<before]
        page=allmessages[-max(1,min(limit,100)):];runs={m['runId']:self.store.get('run',m['runId']) for m in page}
        # A step message keeps its own durable text; the run message only shows
        # the aggregate when the manager answered directly (no employee steps).
        for m in page:
            r=runs.get(m['runId'])
            if m['role']=='assistant' and r:
                if m.get('step'):
                    steps={s['step']:s for s in r.get('steps') or []};s=steps.get(m['step'])
                    m['text']=s.get('text','') if s else m.get('text','');m['status']=s.get('status') if s else r['status'];m['error']=s.get('error') if s else None
                else:
                    m['text']=r.get('answer','') if not r.get('steps') else '';m['status']=r['status']
        return {'conversation':conv,'messages':page,'runs':list(runs.values()),'before':page[0]['sequence'] if len(allmessages)>len(page) else None}
    def step_message(self,run,record):
        cid=run['conversationId'];mid=run['id']+':step:'+str(record['step']);existing=self.store.get('message',mid)
        if existing:
            existing.update(text=record.get('text',''),status=record.get('status'),error=record.get('error'),employee=record.get('employee'))
            self.store.put('message',mid,existing);return existing
        seq=max((m['sequence'] for m in self.messages(cid)),default=0)+1
        value={'id':mid,'conversationId':cid,'projectId':run['workspace'],'runId':run['id'],'role':'assistant','step':record['step'],'employee':record.get('employee'),'requestedModel':record.get('requestedModel'),'text':record.get('text',''),'status':record.get('status'),'error':record.get('error'),'sequence':seq}
        self.store.put('message',mid,value);return value
    def attach(self,run):
        cid=run['conversationId'];conv=self.conversation(cid,run['workspace']);messages=self.messages(cid);seq=max((m['sequence'] for m in messages),default=0)
        records=[('run_link',run['id'],{'runId':run['id'],'conversationId':cid,'projectId':run['workspace']})]
        for i,(role,text) in enumerate([('user',run['text']),('assistant','')],1):
            mid=run['id']+':'+role;records.append(('message',mid,{'id':mid,'conversationId':cid,'projectId':run['workspace'],'runId':run['id'],'role':role,'text':text,'sequence':seq+i}))
        if conv['title']=='新对话':conv['title']=run['text'][:60]
        conv['updated']=stamp();records.append(('conversation',cid,conv));self.store.put_many(records)
    def sync(self,run):
        mid=run['id']+':assistant';msg=self.store.get('message',mid)
        if msg:msg['text']=run.get('answer','');self.store.put('message',mid,msg)
    def history(self,cid,exclude=None):
        msgs=self.messages(cid);result=[];size=0
        for m in reversed(msgs):
            if m['runId']==exclude:continue
            if m['role']=='assistant':r=self.store.get('run',m['runId']);text=r.get('answer','') if r else m['text']
            else:text=m['text']
            if not text:continue
            text=text[:8000];size+=len(text)
            if size>24000:break
            result.append({'role':m['role'],'text':text})
        return list(reversed(result))
    def listing(self,pid=None):
        return sorted([c for c in self.store.all('conversation') if not pid or c['projectId']==pid],key=lambda c:(c['updated'],c['id']),reverse=True)

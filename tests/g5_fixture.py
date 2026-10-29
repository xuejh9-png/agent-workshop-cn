"""Temporary, synthetic browser fixture. Never uses credentials or real models.

Run explicitly, not part of unittest discovery. SIGTERM removes its temporary
data. The real production Handler and app.js are served without UI substitutes.
"""
import json, signal, socket, sys, tempfile, threading, time, uuid
from pathlib import Path
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit,parse_qs
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import Studio,Handler
from file_tools import ScopedFiles

control={}
class FixtureAdapter:
    def __init__(self,host):self.host=host;self.calls=[];self.cancelled=[]
    def catalog(self,refresh=False):return [{'id':self.host+'-g5','name':self.host+' G5 测试替身','efforts':['low','high'],'defaultEffort':'low'}, {'id':self.host+'-unverified','efforts':['low']}]
    def account_identity(self):return {'accountId':'g5-'+self.host,'configId':'fixture'}
    def cancel(self,ident):self.cancelled.append(ident)
    def call(self,ident,model,effort,prompt,cwd,event,cancelled,coordinator=False,writable=False,**kwargs):
        self.calls.append({'id':ident,'host':self.host,'model':model,'effort':effort,'coordinator':coordinator,'writable':writable})
        event({'type':'call.started','role':'coordinator' if coordinator else 'executor','requestedModel':model,'effort':effort})
        text=prompt.rsplit('\n用户：',1)[-1]
        delay=control.get('delay_model_seconds',0)
        deadline=time.monotonic()+delay
        while time.monotonic()<deadline:
            if cancelled():raise InterruptedError('测试替身已停止')
            time.sleep(.03)
        if 'G5_FAIL' in text:raise RuntimeError('G5 人工注入的模型错误')
        answer=('我是 Agent Studio 的项目经理。'+text) if coordinator else self.host+'员工：合成验收结果'
        if 'G5_LONG' in text:answer='\n'.join('第%d段：这是G5合成的长回答，用于检查增量呈现、滚动、停止和刷新。'%i for i in range(1,121))
        tasks=[{'employee':'codex','task':'G5第一步'},{'employee':'claude','task':'G5第二步'}] if 'G5_DELEGATE' in text else []
        result={'route':'delegate' if tasks else 'answer','answer':answer,'task':'','reason':'G5合成测试','tasks':tasks}
        return {'text':json.dumps(result,ensure_ascii=False) if coordinator else answer,'sessionId':'g5-fixture-'+uuid.uuid4().hex,'usage':{'input_tokens':10,'output_tokens':10},'requestedModel':model,'actualModel':None,'role':'coordinator' if coordinator else 'executor'}

class FixtureHandler(Handler):
    def do_GET(self):
        path=urlsplit(self.path).path
        if path=='/fixture/state':
            if not self.trusted():self.send({'error':'forbidden'},403);return
            self.send({'projects':self.app.store.all('project'),'conversations':self.app.projects.listing(),'runs':self.app.store.all('run'),'calls':{h:self.app.adapter_for(h).calls for h in self.app.hosts},'control':control});return
        if path=='/api/progress' and control.get('progress_offline'):
            self.send({'error':'G5 合成断网'},503);return
        query=parse_qs(urlsplit(self.path).query)
        if path=='/api/conversation' and query.get('id',[''])[0]==control.get('delayed_conversation'):
            time.sleep(control.get('delay_conversation_seconds',0))
        if path=='/api/file':time.sleep(control.get('delay_file_seconds',0))
        super().do_GET()
    def do_POST(self):
        path=urlsplit(self.path).path
        if path=='/fixture/control':
            if not self.trusted(True):self.send({'error':'forbidden'},403);return
            value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            control.clear();control.update(value);self.send({'ok':True});return
        if path=='/api/settings' and control.get('settings_fail'):
            self.send({'error':'G5 合成保存失败'},503);return
        super().do_POST()
    def send(self,value,*args,**kwargs):
        if urlsplit(self.path).path=='/api/runs':time.sleep(control.get('delay_run_response',0))
        if urlsplit(self.path).path=='/api/runs' and control.get('drop_run_response_once'):
            control['drop_run_response_once']=False;self.close_connection=True
            self.connection.shutdown(socket.SHUT_RDWR);self.connection.close();return
        super().send(value,*args,**kwargs)

def main():
    with tempfile.TemporaryDirectory(prefix='studio-g5-browser-') as directory:
        app=Studio(Path(directory));app.adapter=FixtureAdapter('codex');app.claude=FixtureAdapter('claude');app.workbuddy=FixtureAdapter('workbuddy')
        first=app.store.all('project')[0];app.projects.rename_project(first['id'],'G5 项目A')
        projects=[app.projects.project(first['id']),app.projects.create_project('G5 项目B'),app.projects.create_project('G5 项目C：较长中文项目名称与独立资料验证')]
        managers={h:{'model':h+'-g5','effort':'low'} for h in app.hosts}
        app.store.put('settings','v2',{'schemaVersion':2,'revision':0,'productName':'Agent Studio','managerHost':'codex','managerModelByHost':managers,'employeeProfilesByHost':{h:{'enabled':True,**p} for h,p in managers.items()},'reviewPolicy':{'enabled':False},'updatedAt':'g5-fixture'})
        app.store.put('settings','verified_v2',{app.config.key(h,h+'-g5',app.config.identity(h)):{'at':'g5-fixture'} for h in app.hosts})
        for index,p in enumerate(projects):
            ScopedFiles(app.root(p['id']),True).create('scope.md','G5项目'+chr(65+index)+'独占资料，禁止串入其他项目。')
            run=app.start_v12({'schemaVersion':2,'projectId':p['id'],'conversationId':None,'text':'G5项目'+chr(65+index)+'历史标记','managerHost':'codex','allowedEmployees':[],'allowWrite':False,'requestId':uuid.uuid4().hex})
            app.workers[run['id']].join(3)
        server=ThreadingHTTPServer(('127.0.0.1',8892),FixtureHandler);server.app=app
        def stop(*args):
            app.stopping=True
            for run in app.store.all('run'):
                if run['status']=='running':app.cancel(run['id'])
            server.server_close();app.store.db.close();raise SystemExit(0)
        signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
        print('G5 synthetic browser fixture at http://127.0.0.1:8892',flush=True);server.serve_forever()

if __name__=='__main__':main()

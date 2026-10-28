"""Local Codex CLI adapter: discovery, bounded processes, durable evidence."""
import hashlib, json, os, selectors, shutil, signal, subprocess, sys, threading, time
from pathlib import Path

ROOT=Path(__file__).resolve().parent
TERMINAL={'completed','failed','cancelled','interrupted','blocked'}
ROUTE_SCHEMA={'type':'object','properties':{'route':{'type':'string','enum':['answer','delegate']},'answer':{'type':'string'},'task':{'type':'string'},'reason':{'type':'string'}},'required':['route','answer','task','reason'],'additionalProperties':False}

# V1 schema remains accepted by the internal legacy bridge; new managers may
# plan several sequential employees. No public request may invoke the bridge.
ROUTE_SCHEMA['properties']['tasks']={'type':'array','maxItems':4,'items':{'type':'object','properties':{'employee':{'type':'string','enum':['codex','claude','workbuddy']},'task':{'type':'string','maxLength':12000}},'required':['employee','task'],'additionalProperties':False}}
ROUTE_SCHEMA['required'].append('tasks')

BUNDLED_CODEX='/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex'

def codex_binary():
    # A GUI-launched shell often lacks the CLI on PATH. Resolve once, explicitly,
    # instead of silently reporting "not installed" while the CLI exists.
    override=os.environ.get('STUDIO_CODEX_BIN')
    if override:
        if not os.access(override,os.X_OK):raise RuntimeError('STUDIO_CODEX_BIN 指向的文件不可执行')
        return override
    found=shutil.which('codex')
    if found:return found
    if os.access(BUNDLED_CODEX,os.X_OK):return BUNDLED_CODEX
    raise RuntimeError('未安装 Codex CLI')

class CodexAdapter:
    def __init__(self, data):
        self.data=Path(data);self.processes={};self.lock=threading.RLock();self.catalog_cache=None
        self.schema=self.data/'coordinator-schema.json';self.schema.write_text(json.dumps(ROUTE_SCHEMA))

    def catalog(self,refresh=False):
        if self.catalog_cache and not refresh:return self.catalog_cache
        binary=codex_binary()
        p=subprocess.Popen([binary,'app-server','--stdio'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,start_new_session=True)
        try:
            for msg in [{'id':1,'method':'initialize','params':{'clientInfo':{'name':'agent_studio','version':'0.2'},'capabilities':{'experimentalApi':True}}},{'method':'initialized'},{'id':2,'method':'model/list','params':{}}]:
                p.stdin.write(json.dumps(msg)+'\n');p.stdin.flush()
            deadline=time.monotonic()+15; sel=selectors.DefaultSelector();sel.register(p.stdout,selectors.EVENT_READ)
            # os.read avoids TextIO buffering hiding a second JSON message from select().
            buf=b''
            while time.monotonic()<deadline:
                for key,_ in sel.select(0.2):
                    chunk=os.read(key.fileobj.fileno(),65536)
                    if not chunk:raise RuntimeError('模型目录服务已退出')
                    buf+=chunk
                    while b'\n' in buf:
                        line,buf=buf.split(b'\n',1);msg=json.loads(line)
                        if msg.get('id')==2:
                            if 'error' in msg:raise RuntimeError('模型目录请求失败')
                            models=[]
                            for m in msg['result'].get('data',[]):
                                models.append({'id':m['id'],'name':m.get('displayName',m['id']),'efforts':[x['reasoningEffort'] for x in m.get('supportedReasoningEfforts',[])],'defaultEffort':m.get('defaultReasoningEffort','low'),'source':'Codex App Server model/list'})
                            self.catalog_cache=models;return models
            raise RuntimeError('模型目录请求超时')
        finally:
            self.terminate(p)

    def account_identity(self):
        # Only an opaque account/configuration binding leaves this method. No
        # email, access token, auth file or private chat is read by the app.
        p=subprocess.Popen([codex_binary(),'app-server','--stdio'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,start_new_session=True)
        try:
            for msg in [{'id':1,'method':'initialize','params':{'clientInfo':{'name':'studio_identity','version':'1.2'}}},{'method':'initialized'},{'id':2,'method':'account/read','params':{'refreshToken':False}}]:
                p.stdin.write((json.dumps(msg)+'\n').encode());p.stdin.flush()
            sel=selectors.DefaultSelector();sel.register(p.stdout,selectors.EVENT_READ);buf=b'';deadline=time.monotonic()+12
            while time.monotonic()<deadline:
                for key,_ in sel.select(.2):
                    chunk=os.read(key.fileobj.fileno(),65536)
                    if not chunk:raise RuntimeError('无法核对Codex登录身份')
                    buf+=chunk
                    while b'\n' in buf:
                        line,buf=buf.split(b'\n',1);msg=json.loads(line)
                        if msg.get('id')==2:
                            account=msg.get('result',{}).get('account')
                            if not account:raise RuntimeError('Codex未登录，请先在CLI完成登录')
                            # A random local namespace prevents exposing a plain email hash.
                            salt=self.data/'connection-namespace'
                            if not salt.exists():
                                import secrets
                                try:
                                    fd=os.open(salt,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                                    with os.fdopen(fd,'w') as f:f.write(secrets.token_hex(32))
                                except FileExistsError:pass
                            namespace=salt.read_text()
                            digest=hashlib.sha256((namespace+json.dumps(account,sort_keys=True)).encode()).hexdigest()
                            return {'accountId':digest,'configId':'codex-studio-https-v1'}
            raise RuntimeError('Codex登录身份核对超时')
        finally:self.terminate(p)

    @staticmethod
    def terminate(p):
        # Kill the process group even when the leader has already exited: MCP
        # descendants may still be alive. A live group reserves its process ID.
        try:os.killpg(p.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:p.wait(timeout=2)
        except subprocess.TimeoutExpired:pass
        # The leader may exit before its MCP child; still kill the group.
        try:os.killpg(p.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        try:p.wait(timeout=3)
        except subprocess.TimeoutExpired:raise RuntimeError('未能确认执行器停止')

    def cancel(self,run_id):
        with self.lock:p=self.processes.get(run_id)
        if p:self.terminate(p)

    def call(self, run_id, model, effort, prompt, cwd, on_event, cancelled, coordinator=False, writable=False):
        cmd=[codex_binary(),'exec','--ignore-user-config','--ephemeral','--skip-git-repo-check','--sandbox','read-only','-C',str(cwd),'-m',model,'--json']
        overrides={'features.shell_tool':False,'features.apply_patch_freeform':False,'web_search':'disabled','model_reasoning_effort':effort,'features.multi_agent':False,'features.apps':False,'features.hooks':False,'features.plugins':False,'features.remote_plugin':False,'features.browser_use':False,'features.browser_use_external':False,'features.computer_use':False,'features.in_app_browser':False,'features.image_generation':False,'features.view_image':False,'model_provider':'studio_https','model_providers.studio_https.name':'OpenAI HTTPS','model_providers.studio_https.wire_api':'responses','model_providers.studio_https.requires_openai_auth':True,'model_providers.studio_https.supports_websockets':False}
        audit=self.data/(run_id+'.audit.jsonl')
        if coordinator:cmd+=['--output-schema',str(self.schema)]
        else:
            args=[str(ROOT/'file_tools.py'),'--root',str(cwd),'--audit',str(audit)]
            if writable:args.append('--write')
            overrides.update({'mcp_servers.studio_files.command':sys.executable,'mcp_servers.studio_files.args':args,'mcp_servers.studio_files.startup_timeout_sec':15,'mcp_servers.studio_files.required':True,'mcp_servers.studio_files.default_tools_approval_mode':'approve','mcp_servers.studio_files.enabled_tools':['read_file','list_files','write_file']})
        for key,value in overrides.items():cmd+=['-c',key+'='+json.dumps(value,ensure_ascii=False)]
        cmd+=['-']
        role='coordinator' if coordinator else 'executor'
        on_event({'type':'call.started','role':role,'requestedModel':model,'effort':effort,'adapter':'codex exec','sandbox':'read-only','shell':False})
        p=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,cwd=cwd,start_new_session=True)
        with self.lock:self.processes[run_id]=p
        on_event({'type':'process.started','pid':p.pid,'processGroup':p.pid,'role':role})
        output='';usage=None;session=None;error=None;buffer=b'';total=0
        try:
            if cancelled():raise InterruptedError('用户已停止')
            p.stdin.write(prompt.encode());p.stdin.close()
            selector=selectors.DefaultSelector();selector.register(p.stdout,selectors.EVENT_READ);deadline=time.monotonic()+180
            while True:
                if cancelled():raise InterruptedError('用户已停止')
                if time.monotonic()>deadline:raise TimeoutError('执行超过 180 秒，已停止本次进程')
                ready=selector.select(.15)
                if not ready and p.poll() is not None:break
                for key,_ in ready:
                    chunk=os.read(key.fileobj.fileno(),65536)
                    if not chunk:selector.unregister(p.stdout);break
                    total+=len(chunk)
                    if total>2_000_000:raise RuntimeError('执行器返回过多内容，已停止')
                    buffer+=chunk
                    while b'\n' in buffer:
                        line,buffer=buffer.split(b'\n',1)
                        try:event=json.loads(line)
                        except ValueError:continue
                        kind=event.get('type','')
                        if kind=='thread.started':session=event.get('thread_id');on_event({'type':kind,'sessionId':session,'role':role})
                        elif kind=='item.started':
                            item=event.get('item',{})
                            if item.get('type')=='mcp_tool_call':on_event({'type':'tool.started','tool':item.get('tool'),'server':item.get('server'),'role':role})
                        elif kind=='item.completed':
                            item=event.get('item',{});typ=item.get('type')
                            if typ=='agent_message':output=item.get('text','')[:150000]
                            elif typ=='mcp_tool_call':
                                failed=item.get('error') is not None or (item.get('result') or {}).get('isError',False)
                                on_event({'type':'tool.completed','tool':item.get('tool'),'server':item.get('server'),'role':role,'error':failed})
                                if failed:raise RuntimeError('文件工具未成功，可能是未授权、文件已存在或路径不允许；操作已停止')
                            elif typ=='command_execution':raise RuntimeError('检测到未开放的命令执行，已停止')
                        elif kind=='turn.completed':usage=event.get('usage');on_event({'type':kind,'usage':usage,'role':role})
                        elif kind in ('error','turn.failed'):
                            raw=event.get('message') or event.get('error',{}).get('message') or '执行器返回失败'
                            # Avoid copying raw provider responses/configuration into API or evidence.
                            error='模型调用失败，请检查登录、模型权限或服务状态'
                            if 'rate' in raw.lower() or 'quota' in raw.lower():error='模型额度或频率受限，请稍后重试'
                            on_event({'type':'call.error','message':error,'role':role})
                if not selector.get_map():break
            code=p.wait(timeout=5)
            if cancelled():raise InterruptedError('用户已停止')
            if code!=0 or not output:raise RuntimeError(error or '模型未返回有效回答，请检查连接与模型权限')
            return {'text':output,'usage':usage,'sessionId':session,'requestedModel':model,'actualModel':None,'role':role,'exitCode':code}
        finally:
            self.terminate(p)
            with self.lock:self.processes.pop(run_id,None)

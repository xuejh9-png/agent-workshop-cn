"""Local Codex CLI adapter: discovery, bounded processes, durable evidence."""
import hashlib, hmac, json, os, selectors, shutil, signal, subprocess, sys, threading, time
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
        # A freshly started app-server can answer before the CLI is ready, which
        # would otherwise surface as a false "not logged in" right after boot.
        try:return self._account_identity_once()
        except RuntimeError:
            time.sleep(1.5)
            return self._account_identity_once()
    def _account_identity_once(self):
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

    def call(self, run_id, model, effort, prompt, cwd, on_event, cancelled, coordinator=False, writable=False, manifest=None):
        cmd=[codex_binary(),'exec','--ignore-user-config','--ephemeral','--skip-git-repo-check','--sandbox','read-only','-C',str(cwd),'-m',model,'--json']
        overrides={'features.shell_tool':False,'features.apply_patch_freeform':False,'web_search':'disabled','model_reasoning_effort':effort,'features.multi_agent':False,'features.apps':False,'features.hooks':False,'features.plugins':False,'features.remote_plugin':False,'features.browser_use':False,'features.browser_use_external':False,'features.computer_use':False,'features.in_app_browser':False,'features.image_generation':False,'features.view_image':False,'model_provider':'studio_https','model_providers.studio_https.name':'OpenAI HTTPS','model_providers.studio_https.wire_api':'responses','model_providers.studio_https.requires_openai_auth':True,'model_providers.studio_https.supports_websockets':False}
        audit=self.data/(run_id+'.audit.jsonl')
        if coordinator:cmd+=['--output-schema',str(self.schema)]
        else:
            args=[str(ROOT/'file_tools.py'),'--root',str(cwd),'--audit',str(audit)]
            if writable:args.append('--write')
            if manifest:args+=['--manifest',str(manifest)]
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


CLAUDE_DEFAULT='/Users/c0437/.local/bin/claude'
# The CLI takes family aliases; the version a given alias resolves to is only
# known after a real call, which is exactly what verification records.
CLAUDE_MODELS=[
    {'id':'opus','name':'Claude Opus 5.5','efforts':['low','medium','high','xhigh','max'],'defaultEffort':'high','source':'Claude Code --model opus'},
    {'id':'sonnet','name':'Claude Sonnet 5.5','efforts':['low','medium','high','xhigh','max'],'defaultEffort':'high','source':'Claude Code --model sonnet'},
    {'id':'haiku','name':'Claude Haiku 5.5','efforts':['low','medium','high'],'defaultEffort':'low','source':'Claude Code --model haiku'},
]

def claude_binary():
    override=os.environ.get('STUDIO_CLAUDE_BIN')
    if override:
        if not os.access(override,os.X_OK):raise RuntimeError('STUDIO_CLAUDE_BIN 指向的文件不可执行')
        return override
    found=shutil.which('claude')
    if found:return found
    if os.access(CLAUDE_DEFAULT,os.X_OK):return CLAUDE_DEFAULT
    raise RuntimeError('未安装 Claude Code CLI')

def claude_settings():
    # Claude Code keeps its endpoint and token in its own settings file. Read it
    # for the child process only; nothing here is logged, returned or stored.
    path=Path(os.environ.get('STUDIO_CLAUDE_SETTINGS',Path.home()/'.claude/settings.json'))
    try:value=json.loads(path.read_text())
    except (OSError,ValueError):return {}
    env=value.get('env') if isinstance(value.get('env'),dict) else {}
    return {k:v for k,v in env.items() if isinstance(v,str) and v}

class ClaudeAdapter:
    """Headless Claude Code as an employee: same scoped file tools, no shell."""
    def __init__(self,data):
        self.data=Path(data);self.processes={};self.lock=threading.RLock()
    def catalog(self,refresh=False):return [dict(m) for m in CLAUDE_MODELS]
    def identity(self):
        cfg=claude_settings();base=cfg.get('ANTHROPIC_BASE_URL','');token=cfg.get('ANTHROPIC_AUTH_TOKEN','')
        if not base or not token:raise RuntimeError('Claude Code 未配置登录，请先在终端完成配置')
        salt=self.data/'connection-namespace'
        if not salt.exists():
            import secrets
            try:
                fd=os.open(salt,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'w') as f:f.write(secrets.token_hex(32))
            except FileExistsError:pass
        namespace=salt.read_text()
        # A keyed local fingerprint invalidates verification when credentials
        # rotate, without persisting credentials or a reusable plain hash.
        return {'accountId':hmac.new(namespace.encode(),('claude:'+base+':'+token).encode(),hashlib.sha256).hexdigest(),'configId':'claude-code-studio-v2'}
    account_identity=identity
    def cancel(self,run_id):
        with self.lock:p=self.processes.get(run_id)
        if p:CodexAdapter.terminate(p)
    def call(self,run_id,model,effort,prompt,cwd,on_event,cancelled,coordinator=False,writable=False,manifest=None):
        cfg=claude_settings();env={**os.environ,**cfg}
        audit=self.data/(run_id+'.audit.jsonl')
        server={'command':sys.executable,'args':[str(ROOT/'file_tools.py'),'--root',str(cwd),'--audit',str(audit)]+(['--write'] if writable else [])}
        if manifest:server['args']+=['--manifest',str(manifest)]
        allowed=['mcp__studio_files__list_files','mcp__studio_files__read_file']+(['mcp__studio_files__write_file'] if writable else [])
        cmd=[claude_binary(),'-p','--output-format','json','--model',model,'--effort',effort,
             '--safe-mode','--restricted','--setting-sources','','--tools','','--disable-slash-commands','--no-session-persistence',
             '--strict-mcp-config','--mcp-config',json.dumps({'mcpServers':{} if coordinator else {'studio_files':server}},ensure_ascii=False),
             '--allowedTools',*allowed,
             # Everything that could read, write or execute outside the scoped
             # broker is denied explicitly rather than left to defaults.
             '--disallowedTools','Bash','Edit','Write','Read','Glob','Grep','WebFetch','WebSearch','Task','NotebookEdit']
        role='coordinator' if coordinator else 'executor'
        on_event({'type':'call.started','role':role,'requestedModel':model,'effort':effort,'adapter':'claude -p','sandbox':'scoped-mcp','shell':False})
        p=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,cwd=str(cwd),start_new_session=True,env=env)
        with self.lock:self.processes[run_id]=p
        on_event({'type':'process.started','pid':p.pid,'processGroup':p.pid,'role':role})
        try:
            if cancelled():raise InterruptedError('用户已停止')
            out,err=p.communicate(input=prompt,timeout=300)
            if cancelled():raise InterruptedError('用户已停止')
            if p.returncode!=0:raise RuntimeError('Claude Code 进程异常退出，请检查连接与运行状态')
            try:value=json.loads(out[out.find('{'):out.rfind('}')+1])
            except ValueError:raise RuntimeError('Claude Code 未返回可解析结果，请检查连接')
            if not isinstance(value,dict) or value.get('is_error'):raise RuntimeError('Claude Code 调用失败，请检查连接、额度与型号权限')
            text=value.get('result')
            if not isinstance(text,str) or not text.strip():raise RuntimeError('Claude Code 返回空回答')
            usage=value.get('usage') or {}
            models=list((value.get('modelUsage') or {}).keys())
            return {'text':text,'usage':{'input_tokens':usage.get('input_tokens'),'output_tokens':usage.get('output_tokens'),'cached_input_tokens':usage.get('cache_read_input_tokens')},
                    'sessionId':value.get('session_id'),'requestedModel':model,'actualModel':models[0] if models else None,'role':role,'costUSD':value.get('total_cost_usd')}
        except subprocess.TimeoutExpired:
            raise TimeoutError('执行超过 300 秒，已停止本次进程')
        finally:
            CodexAdapter.terminate(p)
            with self.lock:self.processes.pop(run_id,None)


WORKBUDDY_CLI='/Applications/WorkBuddy.app/Contents/Resources/app.asar.unpacked/cli/dist/codebuddy-lite-wb.mjs'
# WorkBuddy has additional desktop/team tools beyond the Claude tool names.
# Keep the printed init inventory fail-closed as well as denying these names.
WORKBUDDY_DENIED=['Bash','Edit','Write','Read','Glob','Grep','WebFetch','WebSearch','Task','NotebookEdit',
    'Agent','PowerShell','EnterPlanMode','ExitPlanMode','TaskCreate','TaskGet','TaskUpdate','TaskList',
    'TaskStop','TaskOutput','Skill','AskUserQuestion','StructuredOutput','ToolSearch','DeferExecuteTool',
    'SendMessage','TeamCreate','TeamDelete','ImageGen','ViewImage','LibraryUpload','VideoGen',
    'AudioTranscribe','A2AGetAgentCard','A2ASendMessage','A2AGetTask','A2ACancelTask','ListMcpResources',
    'ReadMcpResource','MessageColleague','SpeakInChannel','ChannelTasks','CreateColleague','CreateChannel','ListColleagues']
def workbuddy_models():
    """Read the CLI's own model list. Hardcoding names here would drift and would
    have missed models the user actually uses (e.g. DeepSeek-V4.1-Flash)."""
    path=Path(workbuddy_cli()).parent.parent/'product.json'
    try:data=json.loads(path.read_text())
    except (OSError,ValueError):raise RuntimeError('无法读取 WorkBuddy 型号目录')
    out=[]
    for m in data.get('models') or []:
        if not m.get('supportsToolCall'):continue
        ident=m.get('id')
        if not ident or ident=='default':continue
        out.append({'id':ident,'name':m.get('name') or ident,'efforts':['low','medium','high','xhigh'],'defaultEffort':'medium','source':'WorkBuddy product.json'})
    if not out:raise RuntimeError('WorkBuddy 型号目录为空')
    return sorted(out,key=lambda m:(m['id']!='auto',m['id']))

def workbuddy_cli():
    # The desktop app ships the CLI but does not put it on PATH. Only the
    # bundled lite bundle is loadable; bin/codebuddy expects a dist it lacks.
    override=os.environ.get('STUDIO_WORKBUDDY_CLI')
    path=Path(override or WORKBUDDY_CLI)
    if not path.is_file():raise RuntimeError('未找到 WorkBuddy 自带的 CodeBuddy CLI')
    return str(path)

def save_workbuddy_key(key):
    """Write the user's key to a private file. Never return or log its content."""
    if not isinstance(key,str) or not key.strip() or len(key.strip())>512 or any(c in key for c in '\r\n\x00'):
        raise ValueError('API Key 格式无效')
    path=Path.home()/'.workbuddy/api-key'
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    from file_tools import ScopedFiles
    import secrets, stat
    directory=ScopedFiles(path.parent);temp='.api-key-'+secrets.token_hex(12)
    try:
        try:
            current=os.stat('api-key',dir_fd=directory.root_fd,follow_symlinks=False)
            if not stat.S_ISREG(current.st_mode) or current.st_nlink!=1:raise ValueError('密钥文件必须是普通文件，不能是链接')
        except FileNotFoundError:pass
        fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=directory.root_fd)
        with os.fdopen(fd,'w') as f:f.write(key.strip());f.flush();os.fsync(f.fileno())
        os.replace(temp,'api-key',src_dir_fd=directory.root_fd,dst_dir_fd=directory.root_fd)
    finally:
        try:os.unlink(temp,dir_fd=directory.root_fd)
        except FileNotFoundError:pass
    return {'host':'workbuddy','configured':True,'path':str(path)}

def workbuddy_key_present():
    try:workbuddy_credentials();return True
    except RuntimeError:return False

def workbuddy_credentials():
    # The key is read from the environment or from a file the user controls.
    # It is never written into the app database, the settings API or the logs.
    for name in ('CODEBUDDY_API_KEY','CODEBUDDY_AUTH_TOKEN'):
        value=os.environ.get(name)
        if value:return name,value
    for path in (Path.home()/'.workbuddy/api-key',Path.home()/'.codebuddy/api-key'):
        try:value=path.read_text().strip()
        except OSError:continue
        if value:return 'CODEBUDDY_API_KEY',value
    settings=Path.home()/'.codebuddy/settings.json'
    try:env=json.loads(settings.read_text()).get('env') or {}
    except (OSError,ValueError):env={}
    for name in ('CODEBUDDY_API_KEY','CODEBUDDY_AUTH_TOKEN'):
        if env.get(name):return name,env[name]
    raise RuntimeError('WorkBuddy 未配置 API Key：请把密钥写入 ~/.workbuddy/api-key（仅本人可读）')

class WorkBuddyAdapter:
    """WorkBuddy's bundled CodeBuddy CLI as an employee, with the same scoped tools."""
    def __init__(self,data):
        self.data=Path(data);self.processes={};self.lock=threading.RLock()
    def catalog(self,refresh=False):return [dict(m) for m in workbuddy_models()]
    def identity(self):
        workbuddy_cli();name,key=workbuddy_credentials()
        salt=self.data/'connection-namespace'
        if not salt.exists():
            import secrets
            try:
                fd=os.open(salt,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'w') as f:f.write(secrets.token_hex(32))
            except FileExistsError:pass
        namespace=salt.read_text()
        return {'accountId':hmac.new(namespace.encode(),('workbuddy:'+name+':'+key).encode(),hashlib.sha256).hexdigest(),'configId':'workbuddy-codebuddy-cli-v2'}
    account_identity=identity
    def cancel(self,run_id):
        with self.lock:p=self.processes.get(run_id)
        if p:CodexAdapter.terminate(p)
    def call(self,run_id,model,effort,prompt,cwd,on_event,cancelled,coordinator=False,writable=False,manifest=None):
        name,key=workbuddy_credentials();env={**os.environ,name:key,'CODEBUDDY_CODE_DISABLE_AUTO_MEMORY':'1'}
        audit=self.data/(run_id+'.audit.jsonl')
        server={'command':sys.executable,'args':[str(ROOT/'file_tools.py'),'--root',str(cwd),'--audit',str(audit)]+(['--write'] if writable else [])}
        if manifest:server['args']+=['--manifest',str(manifest)]
        allowed=['mcp__studio_files__list_files','mcp__studio_files__read_file']+(['mcp__studio_files__write_file'] if writable else [])
        cmd=[shutil.which('node') or 'node',workbuddy_cli(),'-p','--output-format','stream-json','--verbose','--model',model,
             '--setting-sources','','--tools','','--no-session-persistence','--settings','{"disableAllHooks":true,"autoMemoryEnabled":false}',
             '--effort',effort,'--max-turns','12','--strict-mcp-config',
             '--mcp-config',json.dumps({'mcpServers':{} if coordinator else {'studio_files':server}},ensure_ascii=False),
             '--allowedTools',*allowed,
             '--disallowedTools',*WORKBUDDY_DENIED]
        role='coordinator' if coordinator else 'executor'
        on_event({'type':'call.started','role':role,'requestedModel':model,'effort':effort,'adapter':'codebuddy -p','sandbox':'scoped-mcp','shell':False})
        p=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,cwd=str(cwd),start_new_session=True,env=env)
        with self.lock:self.processes[run_id]=p
        on_event({'type':'process.started','pid':p.pid,'processGroup':p.pid,'role':role})
        try:
            if cancelled():raise InterruptedError('用户已停止')
            p.stdin.write(prompt);p.stdin.close()
            selector=selectors.DefaultSelector();selector.register(p.stdout,selectors.EVENT_READ);selector.register(p.stderr,selectors.EVENT_READ)
            deadline=time.monotonic()+300;buffer=b'';total=0;value=None;initialized=False
            while selector.get_map():
                if cancelled():raise InterruptedError('用户已停止')
                if time.monotonic()>deadline:raise TimeoutError('WorkBuddy 执行超时，已停止')
                for ready,_ in selector.select(.15):
                    chunk=os.read(ready.fileobj.fileno(),65536)
                    if not chunk:selector.unregister(ready.fileobj);continue
                    total+=len(chunk)
                    if total>2_000_000:raise RuntimeError('WorkBuddy 返回内容过多，已停止')
                    if ready.fileobj is p.stderr:continue
                    buffer+=chunk
                    while b'\n' in buffer:
                        line,buffer=buffer.split(b'\n',1)
                        try:item=json.loads(line)
                        except ValueError:continue
                        if not isinstance(item,dict):continue
                        if item.get('type')=='system' and item.get('subtype')=='init':
                            actual=item.get('tools');expected=set() if coordinator else set(allowed)
                            if not isinstance(actual,list) or set(actual)!=expected:raise RuntimeError('WorkBuddy 工具范围与本次授权不一致，已停止；请检查 CLI 版本与受限配置')
                            initialized=True
                            on_event({'type':'tools.checked','role':role,'tools':actual})
                        if item.get('type')=='result':value=item
            if p.wait(timeout=5)!=0:raise RuntimeError('WorkBuddy 进程异常退出，请检查连接与运行状态')
            if cancelled():raise InterruptedError('用户已停止')
            if not initialized or not isinstance(value,dict):raise RuntimeError('WorkBuddy 未返回工具范围和完成结果，请检查登录与连接')
            if value.get('is_error') or value.get('subtype')=='error':raise RuntimeError('WorkBuddy 调用失败，请检查登录、额度与型号权限')
            text=value.get('result') if isinstance(value.get('result'),str) else value.get('text')
            if not isinstance(text,str) or not text.strip():raise RuntimeError('WorkBuddy 返回空回答')
            if 'DSML' in text and ('invoke' in text or 'calls' in text):raise RuntimeError('WorkBuddy 返回了未执行的工具调用文本，CLI 没有实际执行文件操作；请改用已验证的 Codex 员工')
            usage=value.get('usage') or {}
            models=[k for k in (value.get('modelUsage') or {})]
            return {'text':text,'usage':{'input_tokens':usage.get('input_tokens'),'output_tokens':usage.get('output_tokens'),'cached_input_tokens':usage.get('cache_read_input_tokens')},
                    'sessionId':value.get('session_id') or value.get('sessionId'),'requestedModel':model,'actualModel':models[0] if models else None,'role':role,'costUSD':value.get('total_cost_usd')}
        except subprocess.TimeoutExpired:
            raise TimeoutError('执行超过 300 秒，已停止本次进程')
        finally:
            CodexAdapter.terminate(p)
            with self.lock:self.processes.pop(run_id,None)

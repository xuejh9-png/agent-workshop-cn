"""Local M1 preview. Read-only CLI version probes; no model/task execution."""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import json, shutil, subprocess
ROOT = Path(__file__).resolve().parent
class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs): super().__init__(*args, directory=str(ROOT), **kwargs)
    def do_GET(self):
        if self.path == '/api/capabilities':
            result=[]
            for command, name in [('codex','Codex'), ('claude','Claude Code'), ('codebuddy','CodeBuddy CLI（非 WorkBuddy 桌面）')]:
                path=shutil.which(command)
                entry={'name':name,'installed':bool(path),'version':None,'note':'未检测到命令；不代表桌面应用未安装'}
                if path:
                    try:
                        proc=subprocess.run([path,'--version'],capture_output=True,text=True,timeout=5)
                        entry['version']=proc.stdout.strip()[:150] if proc.returncode==0 else None
                        entry['note']='版本读取失败' if proc.returncode else '只验证安装；模型与账号未验证'
                    except (OSError,subprocess.TimeoutExpired): entry['note']='版本检测超时或不可执行'
                result.append(entry)
            body=json.dumps({'executors':result,'taskExecution':False},ensure_ascii=False).encode()
            self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
        elif self.path.split('?')[0] not in ('/','/index.html','/app.js'):
            self.send_error(404)
        else: super().do_GET()
if __name__=='__main__':
    print('Agent Studio local preview: http://127.0.0.1:8891',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8891),Handler).serve_forever()

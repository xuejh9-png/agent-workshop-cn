"""Scoped text file broker exposed to Codex as an MCP stdio server."""
import argparse, json, os, stat, sys
from pathlib import Path, PurePosixPath
MAX_FILE = 256 * 1024
EXTENSIONS = {'.md', '.txt'}

class ScopedFiles:
    extensions = EXTENSIONS
    def __init__(self, root, writable=False, audit=None):
        original = Path(root).absolute()
        # macOS has immutable OS aliases /var and /tmp. Canonicalize only
        # those known prefixes; never resolve user-controlled ancestors.
        if sys.platform == 'darwin' and len(original.parts)>1 and original.parts[1] in ('var','tmp'):
            original = Path('/private', *original.parts[1:])
        self.root = original
        fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            for component in original.parts[1:]:
                if component in ('.', '..'): raise ValueError('工作空间路径无效')
                child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd);fd=child
            self.root_fd = fd
        except BaseException:
            os.close(fd);raise
        self.writable = writable
        self.audit = Path(audit) if audit else None

    def __del__(self):
        fd = getattr(self, 'root_fd', None)
        if fd is not None:
            try: os.close(fd)
            except OSError: pass

    def parts(self, name):
        if not isinstance(name, str) or not name or '\\' in name or '\x00' in name:
            raise ValueError('文件路径无效')
        p = PurePosixPath(name)
        if p.is_absolute() or any(x in ('..', '.') or x.startswith('.') for x in p.parts):
            raise ValueError('只能访问当前工作空间中的非隐藏文本文件')
        if len(p.parts) > 8 or len(name) > 240 or p.suffix.lower() not in self.extensions:
            raise ValueError('本阶段仅支持 .md / .txt，且路径最多八级')
        return p.parts

    def parent_fd(self, parts):
        fd = os.dup(self.root_fd)
        try:
            for part in parts[:-1]:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd); fd = nxt
            return fd
        except BaseException:
            os.close(fd); raise

    def log(self, action, path, size):
        if self.audit:
            # Audit contains paths and sizes, never file contents or credentials.
            with self.audit.open('a', encoding='utf-8') as out:
                out.write(json.dumps({'action': action, 'path': path, 'bytes': size}, ensure_ascii=False)+'\n')

    def read(self, name):
        parts = self.parts(name); parent = self.parent_fd(parts)
        try:
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            with os.fdopen(fd, 'rb') as f:
                info = os.fstat(f.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE:
                    raise ValueError('只允许读取不超过 256KB 的普通文本文件，拒绝链接')
                data = f.read(MAX_FILE+1)
                if len(data) > MAX_FILE: raise ValueError('文件过大')
            result = data.decode('utf-8')
            self.log('read', name, len(data)); return result
        finally: os.close(parent)

    def create(self, name, content):
        if not self.writable: raise PermissionError('本次未授权写入，请先在输入框旁开启本次创建文件权限')
        if not isinstance(content, str) or len(content.encode('utf-8')) > MAX_FILE:
            raise ValueError('文本内容超过 256KB 或格式无效')
        parts = self.parts(name); parent = self.parent_fd(parts)
        try:
            fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
            with os.fdopen(fd, 'w', encoding='utf-8') as f: f.write(content)
            self.log('create', name, len(content.encode('utf-8')))
            return {'path':name, 'bytes':len(content.encode('utf-8'))}
        finally: os.close(parent)

    def listing(self):
        # No recursive disk scan. Root-level safe text files only.
        out=[]
        for name in os.listdir(self.root_fd):
            if name.startswith('.') or Path(name).suffix.lower() not in self.extensions: continue
            info=os.stat(name, dir_fd=self.root_fd, follow_symlinks=False)
            if stat.S_ISREG(info.st_mode) and info.st_nlink==1:
                out.append({'path':name,'bytes':info.st_size})
        return sorted(out,key=lambda x:x['path'])[:200]

def serve(root, writable, audit, manifest=None):
    if manifest:
        from project_files import SnapshotFiles
        files=SnapshotFiles(root,writable,audit,manifest)
    else:files=ScopedFiles(root,writable,audit)
    tools=[
        {'name':'list_files','description':'列出当前已授权工作空间根目录的 md/txt 文件。','inputSchema':{'type':'object','properties':{},'additionalProperties':False}},
        {'name':'read_file','description':'读取当前工作空间中的 UTF-8 md/txt 文件，禁止越界和链接。','inputSchema':{'type':'object','properties':{'path':{'type':'string'}},'required':['path'],'additionalProperties':False}},
        {'name':'write_file','description':'仅在本次已授权时，创建新的 UTF-8 md/txt 文件。不允许覆盖已有文件。','inputSchema':{'type':'object','properties':{'path':{'type':'string'},'content':{'type':'string'}},'required':['path','content'],'additionalProperties':False}}]
    for tool in tools:
        tool['annotations']={'readOnlyHint':tool['name']!='write_file','destructiveHint':False,'openWorldHint':False}
    if manifest:
        tools[0]['description']='列出本次明确授权的源码快照文件。'
        tools[1]['description']='读取本次明确授权的 UTF-8 源码快照，不能访问原项目或其他文件。'
        tools[2]['description']='为本次授权文件提出完整替换内容，只修改隔离快照；原项目需独立审核及用户确认后才写入。'
    if not writable:tools=[tool for tool in tools if tool['name']!='write_file']
    tool_calls=0
    for line in sys.stdin:
        try:
            request=json.loads(line); ident=request.get('id'); method=request.get('method'); params=request.get('params',{})
            if ident is None: continue
            if method=='initialize': result={'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'studio-scoped-files','version':'0.2'}}
            elif method=='tools/list': result={'tools':tools}
            elif method=='ping': result={}
            elif method=='tools/call':
                args=params.get('arguments',{}); name=params.get('name');tool_calls+=1
                try:
                    if tool_calls>20: raise ValueError('本次文件工具调用已达 20 次上限')
                    if name=='list_files': value=files.listing()
                    elif name=='read_file': value=files.read(args.get('path'))
                    elif name=='write_file': value=files.create(args.get('path'),args.get('content'))
                    else: raise ValueError('不支持的工具')
                    result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}],'isError':False}
                except (OSError,ValueError,UnicodeError) as error:
                    result={'content':[{'type':'text','text':str(error)}],'isError':True}
            else:
                print(json.dumps({'jsonrpc':'2.0','id':ident,'error':{'code':-32601,'message':'Method not found'}}),flush=True);continue
            print(json.dumps({'jsonrpc':'2.0','id':ident,'result':result},ensure_ascii=False),flush=True)
        except (ValueError,TypeError):
            continue

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--audit',required=True);parser.add_argument('--write',action='store_true');parser.add_argument('--manifest')
    a=parser.parse_args();serve(a.root,a.write,a.audit,a.manifest)

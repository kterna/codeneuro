"""Project-scoped remote identities, lexical paths, and safe operation boundaries.

Remote metadata is client-attested. No native workstation path is inspected on the
Hub filesystem. Human review capabilities are intentionally absent from RPC.
"""
from datetime import datetime, timedelta
import hashlib
import hmac
import json
from pathlib import PurePosixPath, PureWindowsPath
import re
import secrets
import uuid

from .database import Conflict, DomainError
from .models import AgentIssue, IssueType, Project, Proposal, Task, WorktreeInstance
from .paths import relative_path
from .service import ContextService


def _now():
    return datetime.utcnow().isoformat()


def _id(prefix):
    return prefix + '_' + uuid.uuid4().hex


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def _text(value, label, limit=1000, *, empty=False):
    if not isinstance(value, str) or '\0' in value or len(value) > limit or (not empty and not value.strip()):
        raise DomainError(f'{label} must be a bounded non-empty string.' if not empty else f'{label} must be a bounded string.')
    return value


def _windows_parts(parts):
    for part in parts:
        if (':' in part or part.endswith(('.', ' ')) or
                re.fullmatch(r'(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', part)):
            raise DomainError('Windows device names, alternate streams and normalized aliases are forbidden.')


def normalize_remote_workspace(workspace_path: str, platform: str) -> str:
    """Canonical native absolute spelling without using the Hub filesystem."""
    _text(workspace_path, 'workspace_path', 4096)
    if platform not in ('windows', 'linux', 'macos'):
        raise DomainError('Remote platform must be windows, linux or macos.')
    if '\x00' in workspace_path or '..' in workspace_path.replace('\\', '/').split('/'):
        raise DomainError('Workspace paths must not contain traversal.')
    if platform == 'windows':
        if workspace_path.startswith(('\\\\?\\', '\\\\.\\')):
            raise DomainError('Windows device namespaces are unsupported.')
        path = PureWindowsPath(workspace_path)
        if not path.is_absolute():
            raise DomainError('Windows workspace needs an absolute drive or UNC path.')
        _windows_parts(path.parts[1:])
        return str(path)
    if '\\' in workspace_path:
        raise DomainError('POSIX workspace paths must use forward slashes.')
    path = PurePosixPath(workspace_path)
    if not path.is_absolute() or str(path).startswith('//'):
        raise DomainError('POSIX workspace needs an absolute path.')
    return str(path)


def normalize_remote_file(workspace_path: str, platform: str, file_path: str) -> str:
    """Accept native absolute or relative input and return an anchored POSIX path."""
    root = normalize_remote_workspace(workspace_path, platform)
    _text(file_path, 'file_path', 4096)
    if '..' in file_path.replace('\\', '/').split('/'):
        raise DomainError('File paths must not contain traversal.')
    if platform == 'windows':
        path = PureWindowsPath(file_path)
        if path.drive or path.root:
            if not path.is_absolute():
                raise DomainError('Drive-relative and root-relative Windows paths are ambiguous.')
            try:
                path = path.relative_to(PureWindowsPath(root))
            except ValueError:
                raise DomainError('Remote file is outside its registered workspace.') from None
        _windows_parts(path.parts)
        return relative_path(path.as_posix())
    if re.match(r'^[A-Za-z]:', file_path) or '\\' in file_path:
        raise DomainError('POSIX remote files must use POSIX paths.')
    path = PurePosixPath(file_path)
    if path.is_absolute():
        try:
            path = path.relative_to(PurePosixPath(root))
        except ValueError:
            raise DomainError('Remote file is outside its registered workspace.') from None
    return relative_path(str(path))


def ensure_schema(storage):
    with storage.transaction():
        storage.conn.execute('''CREATE TABLE IF NOT EXISTS remote_clients(
            id TEXT PRIMARY KEY,name TEXT NOT NULL,token_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,revoked_at TEXT,last_used_at TEXT)''')
        storage.conn.execute('''CREATE TABLE IF NOT EXISTS remote_client_projects(
            client_id TEXT NOT NULL REFERENCES remote_clients(id),
            project_id TEXT NOT NULL REFERENCES projects(id),PRIMARY KEY(client_id,project_id))''')
        storage.conn.execute('''CREATE TABLE IF NOT EXISTS remote_workspaces(
            worktree_id TEXT PRIMARY KEY REFERENCES worktree_instances(id),
            client_id TEXT NOT NULL REFERENCES remote_clients(id),platform TEXT NOT NULL,
            canonical_path TEXT NOT NULL,repo_identity TEXT,metadata_trust TEXT NOT NULL DEFAULT 'client_attested',
            created_at TEXT NOT NULL)''')
        storage.conn.execute('''CREATE TABLE IF NOT EXISTS remote_session_bindings(
            session_id TEXT PRIMARY KEY REFERENCES agent_sessions(id),
            client_id TEXT NOT NULL REFERENCES remote_clients(id),binding_revision INTEGER NOT NULL DEFAULT 0)''')
        storage.conn.execute('''CREATE TABLE IF NOT EXISTS remote_operations(
            id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES agent_sessions(id),
            request_id TEXT NOT NULL,payload_hash TEXT NOT NULL,kind TEXT NOT NULL,paths_json TEXT NOT NULL,
            task_id TEXT,binding_revision INTEGER NOT NULL,status TEXT NOT NULL DEFAULT 'active',
            started_at TEXT NOT NULL,lease_until TEXT NOT NULL,ended_at TEXT,reason TEXT,
            UNIQUE(session_id,request_id))''')
        storage.conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS remote_one_operation ON remote_operations(session_id) WHERE status='active'")
        storage.conn.execute('CREATE INDEX IF NOT EXISTS remote_sessions_owner ON remote_session_bindings(client_id)')


class RemoteRegistry:
    def __init__(self, storage, *, context_service=None, governance=None, intelligence=None, lease_seconds=1800):
        if not isinstance(lease_seconds, int) or not 1 <= lease_seconds <= 7200:
            raise DomainError('Operation lease must be between 1 and 7200 seconds.')
        self.storage = storage
        self.context = context_service or ContextService(storage)
        self.governance = governance
        self.intelligence = intelligence
        self.lease_seconds = lease_seconds
        ensure_schema(storage)

    def _client(self, client_id, *, active=True):
        row = self.storage.conn.execute('SELECT * FROM remote_clients WHERE id=?', (client_id,)).fetchone()
        if row is None or (active and row['revoked_at'] is not None):
            raise DomainError('Client credential is invalid or revoked.', 'unauthorized', 401)
        return dict(row)

    def _public_client(self, row):
        result = {key: row[key] for key in ('id', 'name', 'created_at', 'revoked_at', 'last_used_at')}
        result['project_ids'] = [r[0] for r in self.storage.conn.execute(
            'SELECT project_id FROM remote_client_projects WHERE client_id=? ORDER BY project_id', (row['id'],))]
        return result

    def enroll(self, name, project_ids, *, admin_configured):
        if admin_configured is not True:
            raise DomainError('Configure administrator authentication before issuing client credentials.', 'admin_auth_required', 403)
        _text(name, 'Client name', 200)
        if not isinstance(project_ids, list) or not 1 <= len(project_ids) <= 100 or any(not isinstance(p, str) for p in project_ids):
            raise DomainError('Client enrollment requires one to 100 explicit project IDs.')
        with self.storage.transaction():
            for project_id in project_ids:
                self.storage.validate_scope(project_id)
            client_id = _id('client')
            token = 'cn1_' + client_id + '.' + secrets.token_urlsafe(32)
            self.storage.conn.execute('INSERT INTO remote_clients(id,name,token_hash,created_at) VALUES(?,?,?,?)',
                                      (client_id, name, hashlib.sha256(token.encode()).hexdigest(), _now()))
            for project_id in sorted(set(project_ids)):
                self.storage.conn.execute('INSERT INTO remote_client_projects VALUES(?,?)', (client_id, project_id))
                self.storage.audit(project_id, 'human', 'client.enrolled', client_id, {'name': name})
            return {**self._public_client(self._client(client_id)), 'token': token}

    def list_clients(self):
        with self.storage.transaction(write=False):
            return [self._public_client(dict(row)) for row in self.storage.conn.execute('SELECT * FROM remote_clients ORDER BY created_at')]

    def revoke(self, client_id):
        with self.storage.transaction():
            row = self._client(client_id, active=False)
            if row['revoked_at'] is None:
                self.storage.conn.execute('UPDATE remote_clients SET revoked_at=? WHERE id=?', (_now(), client_id))
                for project_id in self._public_client(row)['project_ids']:
                    self.storage.audit(project_id, 'human', 'client.revoked', client_id, {})
            return self._public_client(self._client(client_id, active=False))

    def authenticate(self, token):
        if not isinstance(token, str) or len(token) > 500:
            token = ''
        match = re.fullmatch(r'cn1_(client_[a-f0-9]{32})\.([A-Za-z0-9_-]{43})', token)
        client_id = match[1] if match else ''
        supplied = hashlib.sha256(token.encode()).hexdigest()
        with self.storage.transaction():
            row = self.storage.conn.execute('SELECT * FROM remote_clients WHERE id=?', (client_id,)).fetchone()
            expected = row['token_hash'] if row else '0' * 64
            valid = hmac.compare_digest(supplied, expected)
            if not valid or row is None or row['revoked_at'] is not None:
                raise DomainError('Client credential is invalid or revoked.', 'unauthorized', 401)
            self.storage.conn.execute('UPDATE remote_clients SET last_used_at=? WHERE id=?', (_now(), client_id))
            return self._public_client(self._client(client_id))

    def authorize_project(self, client_id, project_id):
        with self.storage.transaction(write=False):
            self._client(client_id)
            if not self.storage.conn.execute('SELECT 1 FROM remote_client_projects WHERE client_id=? AND project_id=?',
                                             (client_id, project_id)).fetchone():
                raise DomainError('Client is not authorized for this project.', 'forbidden', 403)
            self.storage.validate_scope(project_id)

    def _workspace(self, client_id, worktree_id):
        self._client(client_id)
        row = self.storage.conn.execute('''SELECT w.*,r.platform,r.repo_identity,r.metadata_trust,r.canonical_path
            FROM worktree_instances w JOIN remote_workspaces r ON w.id=r.worktree_id
            WHERE w.id=? AND r.client_id=?''', (worktree_id, client_id)).fetchone()
        if row is None:
            raise DomainError('Client workspace not found.', 'not_found', 404)
        self.authorize_project(client_id, row['project_id'])
        return dict(row)

    def _session(self, client_id, session_id, *, active=True):
        self._client(client_id)
        row = self.storage.conn.execute('''SELECT s.*,b.binding_revision,b.client_id,r.platform,
            w.worktree_path,w.machine_name FROM agent_sessions s
            JOIN remote_session_bindings b ON s.id=b.session_id
            JOIN remote_workspaces r ON s.worktree_id=r.worktree_id
            JOIN worktree_instances w ON w.id=s.worktree_id
            WHERE s.id=? AND b.client_id=? AND r.client_id=?''', (session_id, client_id, client_id)).fetchone()
        if row is None:
            raise DomainError('Client session not found.', 'not_found', 404)
        self.authorize_project(client_id, row['project_id'])
        if active and row['state'] != 'active':
            raise Conflict('Agent session has been closed.')
        return dict(row)

    def normalize_file(self, client_id, session_id, file_path):
        with self.storage.transaction(write=False):
            session = self._session(client_id, session_id)
            return normalize_remote_file(session['worktree_path'], session['platform'], file_path)

    def start_session(self, client_id, *, project_id, workspace_path, machine_name, platform,
                      git_branch='', git_commit=None, repo_identity=None, task_id=None,
                      agent_client='Remote MCP', debug=False):
        native = normalize_remote_workspace(workspace_path, platform)
        _text(machine_name, 'machine_name', 255);_text(git_branch, 'git_branch', 1000, empty=True)
        _text(agent_client, 'agent_client', 200)
        if git_commit is not None:
            _text(git_commit, 'git_commit', 128)
        if repo_identity is not None:
            _text(repo_identity, 'repo_identity', 1000)
        if not isinstance(debug, bool):
            raise DomainError('debug must be a boolean.')
        canonical = native.casefold() if platform == 'windows' else native
        identity = _json([client_id, project_id, machine_name, platform, canonical])
        worktree_id = 'wt_remote_' + hashlib.sha256(identity.encode()).hexdigest()[:32]
        with self.storage.transaction():
            self.authorize_project(client_id, project_id)
            self.storage.validate_scope(project_id, task_id, require_active=True)
            existing = self.storage.conn.execute('SELECT worktree_path FROM worktree_instances WHERE id=?', (worktree_id,)).fetchone()
            if existing:
                native = existing['worktree_path']
            self.storage.register_worktree_heartbeat(WorktreeInstance(id=worktree_id,project_id=project_id,
                machine_name=machine_name,worktree_path=native,git_branch=git_branch,git_commit=git_commit,
                active_task_id=task_id,agent_client=agent_client,source='remote'))
            # Core heartbeat intentionally does not accept arbitrary source rewrites.
            self.storage.conn.execute("UPDATE worktree_instances SET source='remote' WHERE id=?", (worktree_id,))
            self.storage.conn.execute('''INSERT INTO remote_workspaces(worktree_id,client_id,platform,canonical_path,repo_identity,created_at)
                VALUES(?,?,?,?,?,?) ON CONFLICT(worktree_id) DO UPDATE SET repo_identity=excluded.repo_identity''',
                (worktree_id,client_id,platform,canonical,repo_identity,_now()))
            session_id = _id('session')
            self.storage.conn.execute('''INSERT INTO agent_sessions
                (id,project_id,worktree_id,task_id,agent_client,debug,created_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?)''',
                (session_id,project_id,worktree_id,task_id,agent_client,int(debug),_now(),_now()))
            self.storage.conn.execute('INSERT INTO remote_session_bindings(session_id,client_id) VALUES(?,?)', (session_id,client_id))
            self.storage.audit(project_id, client_id, 'session.started', session_id,
                               {'worktree_id':worktree_id,'task_id':task_id,'metadata_trust':'client_attested','platform':platform})
            return self._session(client_id, session_id)

    def _operation(self, row):
        result = dict(row)
        result['operation_id'] = result['id']
        result['paths'] = json.loads(result.pop('paths_json'))
        result.pop('payload_hash', None)
        result['lease_expired'] = result['status'] == 'active' and result['lease_until'] <= _now()
        result['outcome_scope'] = 'Tool operation completion only; this is not a test result.'
        return result

    def _active_operation(self, session_id):
        row = self.storage.conn.execute("SELECT * FROM remote_operations WHERE session_id=? AND status='active'", (session_id,)).fetchone()
        return self._operation(row) if row else None

    def session_status(self, client_id, session_id):
        with self.storage.transaction(write=False):
            session = self._session(client_id, session_id, active=False)
            return {**session, 'active_operation':self._active_operation(session_id)}

    def _require_idle(self, session_id):
        active = self._active_operation(session_id)
        if active:
            if active['lease_expired']:
                raise Conflict('Operation lease expired but completion is unverified. Explicitly reconcile the actual tool before rebinding or closing.')
            raise Conflict('An actual tool operation is still active. Retry after its completion boundary.')

    def bind_task(self, client_id, session_id, task_id, expected_revision):
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
            raise DomainError('expected_revision must be a non-negative integer.')
        with self.storage.transaction():
            session = self._session(client_id, session_id)
            if session['binding_revision'] != expected_revision:
                raise Conflict('Session task binding changed; inspect its current revision.')
            self._require_idle(session_id)
            self.storage.validate_scope(session['project_id'], task_id, require_active=True)
            if task_id == session['task_id']:
                return session
            self.storage.conn.execute('UPDATE agent_sessions SET task_id=?,last_seen_at=? WHERE id=?', (task_id,_now(),session_id))
            self.storage.conn.execute('UPDATE remote_session_bindings SET binding_revision=binding_revision+1 WHERE session_id=?', (session_id,))
            self.storage.audit(session['project_id'],client_id,'session.task_bound',session_id,
                               {'old_task_id':session['task_id'],'task_id':task_id,'binding_revision':expected_revision+1})
            return self._session(client_id,session_id)

    def start_operation(self, client_id, session_id, kind, paths, request_id):
        _text(request_id, 'request_id', 240)
        if kind not in ('read','edit','write','test','search','inspect','preflight','file_read','file_edit','terminal'):
            raise DomainError('Unsupported operation kind.')
        if not isinstance(paths,list) or not 1 <= len(paths) <= 500:
            raise DomainError('An operation requires one to 500 actual workspace paths.')
        with self.storage.transaction():
            session = self._session(client_id,session_id)
            normalized = list(dict.fromkeys(normalize_remote_file(session['worktree_path'],session['platform'],p) for p in paths))
            fingerprint = hashlib.sha256(_json({'kind':kind,'paths':normalized}).encode()).hexdigest()
            old = self.storage.conn.execute('SELECT * FROM remote_operations WHERE session_id=? AND request_id=?', (session_id,request_id)).fetchone()
            if old:
                if old['payload_hash'] != fingerprint or old['binding_revision'] != session['binding_revision']:
                    raise Conflict('Operation request ID was reused with a different payload or task binding.')
                return self._operation(old)
            self._require_idle(session_id)
            operation_id = _id('operation')
            self.storage.conn.execute('''INSERT INTO remote_operations
                (id,session_id,request_id,payload_hash,kind,paths_json,task_id,binding_revision,started_at,lease_until)
                VALUES(?,?,?,?,?,?,?,?,?,?)''', (operation_id,session_id,request_id,fingerprint,kind,_json(normalized),
                    session['task_id'],session['binding_revision'],_now(),(datetime.utcnow()+timedelta(seconds=self.lease_seconds)).isoformat()))
            self.storage.conn.execute('UPDATE agent_sessions SET last_seen_at=? WHERE id=?', (_now(),session_id))
            self.storage.conn.execute('UPDATE worktree_instances SET last_heartbeat=?,is_online=1 WHERE id=?', (_now(),session['worktree_id']))
            self.storage.audit(session['project_id'],client_id,'operation.started',operation_id,{'session_id':session_id,'kind':kind,'paths':normalized})
            return self._operation(self.storage.conn.execute('SELECT * FROM remote_operations WHERE id=?',(operation_id,)).fetchone())

    def end_operation(self, client_id, session_id, operation_id, status):
        if status not in ('completed','failed','cancelled'):
            raise DomainError('Operation status must be completed, failed or cancelled; test results are separate.')
        with self.storage.transaction():
            session = self._session(client_id,session_id,active=False)
            row = self.storage.conn.execute('SELECT * FROM remote_operations WHERE id=? AND session_id=?', (operation_id,session_id)).fetchone()
            if row is None:
                raise DomainError('Operation not found in this session.', 'not_found',404)
            if row['status'] != 'active':
                if row['status'] != status:
                    raise Conflict('Operation already ended with a different disposition.')
                return self._operation(row)
            self.storage.conn.execute('UPDATE remote_operations SET status=?,ended_at=? WHERE id=?', (status,_now(),operation_id))
            self.storage.audit(session['project_id'],client_id,'operation.ended',operation_id,{'session_id':session_id,'status':status,'test_result':False})
            return self._operation(self.storage.conn.execute('SELECT * FROM remote_operations WHERE id=?',(operation_id,)).fetchone())

    def reconcile_operation(self, client_id, session_id, operation_id, reason, confirmed_finished):
        _text(reason,'reconciliation reason',3000)
        if confirmed_finished is not True:
            raise DomainError('Reconciliation requires explicit confirmation that the actual process/tool has finished.', 'confirmation_required',403)
        with self.storage.transaction():
            session = self._session(client_id,session_id,active=False)
            row = self.storage.conn.execute('SELECT * FROM remote_operations WHERE id=? AND session_id=?',(operation_id,session_id)).fetchone()
            if row is None:
                raise DomainError('Operation not found.', 'not_found',404)
            if row['status']=='reconciled':
                return self._operation(row)
            if row['status']!='active' or row['lease_until']>_now():
                raise Conflict('Only expired, unresolved operation leases can be reconciled.')
            self.storage.conn.execute("UPDATE remote_operations SET status='reconciled',ended_at=?,reason=? WHERE id=?",(_now(),reason,operation_id))
            self.storage.audit(session['project_id'],client_id,'operation.reconciled',operation_id,
                               {'reason':reason,'completion_evidence':'client_attested','test_result':False})
            return self._operation(self.storage.conn.execute('SELECT * FROM remote_operations WHERE id=?',(operation_id,)).fetchone())

    # Exact RPC fields prevent credentials from invoking human-only methods or
    # smuggling flags such as reviewed=True into a loosely dispatched function.
    RPC_FIELDS = {
        'list_projects': (set(), set()),
        'list_tasks': ({'project_id'}, set()),
        'create_task': ({'project_id','title'}, {'description'}),
        'start_session': ({'project_id','workspace_path','machine_name','platform'}, {'git_branch','git_commit','repo_identity','task_id','agent_client','debug'}),
        'session_status': ({'session_id'}, set()),
        'bind_task': ({'session_id','task_id','expected_revision'}, set()),
        'start_operation': ({'session_id','kind','paths','request_id'}, set()),
        'end_operation': ({'session_id','operation_id','status'}, set()),
        'reconcile_operation': ({'session_id','operation_id','reason','confirmed_finished'}, set()),
        'context': ({'session_id','file_path'}, {'request_id','max_chars'}),
        'feedback': ({'session_id','delivery_id','rule_id','score'}, {'reason'}),
        'finding': ({'session_id','target_path','text'}, {'priority'}),
        'issue': ({'session_id','issue_type','title','description','file_path'}, {'related_rule_ids','suggested_action'}),
        'list_rules': ({'session_id'}, set()),
        'propose_contract': ({'session_id','target_component','proposed_contract','justification'}, set()),
        'create_rule': ({'session_id','title','content_points','scope_patterns','reason'}, {'priority','activate','evidence_ids','half_life_days'}),
        'mutate_rule': ({'session_id','rule_id','expected_version','action','reason'}, {'title','content_points','scope_patterns','priority'}),
        'observe_rule': ({'session_id','rule_id','expected_version','test_run_id','supports','reason'}, set()),
        'test_run': ({'session_id','request_id','command','exit_code','started_at','finished_at','paths'}, {'stdout','stderr'}),
        'preflight': ({'session_id','request_id','files','plan'}, {'diff'}),
        'cleanup': ({'session_id'}, {'request_id','close'}),
        'close_session': ({'session_id'}, set()),
        'export_rules': ({'session_id'}, set()),
        'index_manifest': ({'worktree_id','manifest'}, set()),
        'graph': ({'project_id'}, {'worktree_id','path'}),
        'index_graph': ({'project_id'}, {'worktree_id','path'}),
        'inspector': ({'project_id','path'}, {'task_id','days','worktree_id'}),
    }

    def _authorize_rpc(self, client_id, op, args):
        self._client(client_id)
        if not isinstance(args,dict) or op not in self.RPC_FIELDS:
            raise DomainError('Unsupported client operation.', 'forbidden',403)
        required,optional = self.RPC_FIELDS[op]
        if required - args.keys() or args.keys() - required - optional:
            raise DomainError('Missing or unsupported arguments for ' + op + '.')
        if len(_json(args)) > 40_000_000:
            raise DomainError('Client request exceeds the 40 MB bound.')
        for key in ('project_id','session_id','worktree_id','rule_id','delivery_id','test_run_id','operation_id','request_id'):
            if key in args and args[key] is not None:
                _text(args[key],key,240)
        if args.get('task_id') is not None:
            _text(args['task_id'],'task_id',128)
        for key in ('paths','files','command','content_points','scope_patterns','related_rule_ids','evidence_ids'):
            if key in args:
                value = args[key]
                if not isinstance(value,list) or len(value)>500 or any(not isinstance(item,str) or len(item)>30000 for item in value):
                    raise DomainError(key + ' must be a bounded list of strings.')
        for key in ('debug','activate','supports','close','confirmed_finished'):
            if key in args and not isinstance(args[key],bool):
                raise DomainError(key + ' must be a boolean.')
        for key in ('score','expected_version','expected_revision','exit_code','max_chars','days'):
            if key in args and (not isinstance(args[key],int) or isinstance(args[key],bool)):
                raise DomainError(key + ' must be an integer.')
        if 'priority' in args and args['priority'] not in ('P0','P1','P2'):
            raise DomainError('priority must be P0, P1 or P2.')
        if 'manifest' in args and not isinstance(args['manifest'],dict):
            raise DomainError('manifest must be an object.')

        if 'project_id' in args:
            self.authorize_project(client_id,args['project_id'])
        if 'session_id' in args:
            self._session(client_id,args['session_id'],active=op not in {'cleanup','close_session','session_status','end_operation','reconcile_operation'})
        if 'worktree_id' in args and args['worktree_id'] is not None:
            wt = self._workspace(client_id,args['worktree_id'])
            if 'project_id' in args and args['project_id'] != wt['project_id']:
                raise DomainError('Workspace belongs to another project.')

    def rpc(self, client_id, op, args=None):
        args = dict(args or {})
        # Provider calls must not hold a database transaction. The governance
        # preflight validates its snapshot again after provider I/O.
        if op == 'preflight':
            with self.storage.transaction(write=False):
                self._authorize_rpc(client_id,op,args)
                session = self._session(client_id,args['session_id'])
                args['files'] = [normalize_remote_file(session['worktree_path'],session['platform'],p) for p in args['files']]
                governance = self._require(self.governance,'governance')
            result = governance.preflight(**args)
            with self.storage.transaction(write=False):
                self._authorize_rpc(client_id,op,args)  # Revocation during provider I/O prevents applying its answer.
            return self._serialize(result)
        with self.storage.transaction():
            self._authorize_rpc(client_id,op,args)
            result = self._serialize(self._dispatch(client_id,op,args))
        if op == 'cleanup' and self.governance is not None:
            self.governance.process_pending_distillations()
        return result

    @staticmethod
    def _require(service,label):
        if service is None:
            raise DomainError(label + ' service is not configured.', 'service_unavailable',503)
        return service

    @staticmethod
    def _serialize(value):
        if hasattr(value,'model_dump'):
            return value.model_dump(mode='json')
        if isinstance(value,list):
            return [RemoteRegistry._serialize(v) for v in value]
        if isinstance(value,dict):
            return {k:RemoteRegistry._serialize(v) for k,v in value.items()}
        if isinstance(value,datetime):
            return value.isoformat()
        return value

    def _dispatch(self, client_id, op, args):
        if op == 'list_projects':
            ids = self._public_client(self._client(client_id))['project_ids']
            # Local server filesystem roots are not needed by remote clients.
            return [{**p.model_dump(mode='json'),'root_paths':[]} for pid in ids if (p:=self.storage.get_project(pid))]
        if op == 'list_tasks':
            return self.storage.list_tasks(args['project_id'])
        if op == 'create_task':
            _text(args['title'],'title',500);_text(args.get('description',''),'description',30000,empty=True)
            task = self.storage.create_task(Task(id=_id('task'),**args))
            self.storage.audit(task.project_id,client_id,'task.created',task.id,{'source':'remote_client'})
            return task
        if op in {'start_session','session_status','bind_task','start_operation','end_operation','reconcile_operation'}:
            return getattr(self,op)(client_id,**args)
        session = self._session(client_id,args['session_id'],active=op not in {'cleanup','close_session'}) if 'session_id' in args else None
        if op == 'context':
            args['file_path'] = normalize_remote_file(session['worktree_path'],session['platform'],args['file_path'])
            return self.context.resolve(**args)
        if op == 'feedback':
            return self.context.evaluate(**args)
        if op == 'finding':
            args['target_path'] = normalize_remote_file(session['worktree_path'],session['platform'],args['target_path'])
            return self.context.record_finding(**args)
        if op == 'issue':
            if not session['debug']:
                raise DomainError('Debug feedback is disabled for this session.','debug_disabled',403)
            path = normalize_remote_file(session['worktree_path'],session['platform'],args['file_path'])
            for rule_id in args.get('related_rule_ids',[]):
                rule = self.storage.get_rule(rule_id)
                if not rule or rule.project_id != session['project_id']:
                    raise DomainError('Issue references a rule outside the authorized project.')
            _text(args['title'],'title',500);_text(args['description'],'description',30000)
            _text(args.get('suggested_action',''),'suggested_action',30000,empty=True)
            issue = self.storage.record_issue(AgentIssue(id=_id('issue'),project_id=session['project_id'],
                session_id=session['id'],source='agent',issue_type=IssueType(args['issue_type']),title=args['title'],
                description=args['description'],file_path=path,related_rule_ids=args.get('related_rule_ids',[]),
                suggested_action=args.get('suggested_action','')))
            self.storage.audit(session['project_id'],client_id,'issue.created',issue.id,{'session_id':session['id'],'source':'remote_client'})
            return issue
        if op in {'list_rules','export_rules'}:
            rules = self.context.eligible_rules(session['project_id'],session['task_id'])
            if op == 'list_rules':
                return rules
            return {'project_id':session['project_id'],'task_id':session['task_id'],
                    'binding_revision':session['binding_revision'],'rules':rules}
        if op == 'propose_contract':
            _text(args['proposed_contract'],'proposed_contract',30000);_text(args['justification'],'justification',30000)
            proposal = self.storage.create_proposal(Proposal(id=_id('proposal'),project_id=session['project_id'],
                task_id=session['task_id'],target_component=relative_path(args['target_component'],pattern=True),
                proposed_contract=args['proposed_contract'],justification=args['justification'],status='pending'))
            self.storage.audit(session['project_id'],client_id,'proposal.created',proposal.id,{'session_id':session['id'],'review_required':True})
            return proposal
        if op in {'create_rule','mutate_rule','observe_rule','test_run'}:
            governance = self._require(self.governance,'governance')
            if op == 'test_run':
                args['paths'] = [normalize_remote_file(session['worktree_path'],session['platform'],p) for p in args['paths']]
                return governance.record_test_run(**args)
            method = {'create_rule':'create_rule','mutate_rule':'mutate_rule','observe_rule':'observe_rule'}[op]
            return getattr(governance,method)(**args)
        if op in {'cleanup','close_session'}:
            self._require_idle(session['id'])
            if op == 'cleanup':
                return self._require(self.governance,'governance').cleanup_session(**args)
            return self.context.close_session(session['id'])
        if op == 'index_manifest':
            wt = self._workspace(client_id,args['worktree_id'])
            return self._require(self.intelligence,'intelligence').ingest_manifest(wt['project_id'],wt['id'],args['manifest'],source='client')
        if op in {'graph','index_graph'}:
            if not args.get('worktree_id'):
                own = self.storage.conn.execute('''SELECT r.worktree_id FROM remote_workspaces r
                    JOIN worktree_instances w ON r.worktree_id=w.id WHERE r.client_id=? AND w.project_id=?''',
                    (client_id,args['project_id'])).fetchall()
                if len(own)!=1:
                    raise DomainError('Select an owned worktree_id explicitly for this project.')
                args['worktree_id'] = own[0][0]
            return self._require(self.intelligence,'intelligence').graph(**args)
        if op == 'inspector':
            return self.inspector(client_id,**args)
        raise DomainError('Unsupported client operation.','forbidden',403)

    def inspector(self, client_id, project_id, path, task_id=None, days=7, worktree_id=None):
        with self.storage.transaction(write=False):
            return self._inspect_owned(client_id,project_id,path,task_id,days,worktree_id)

    def _inspect_owned(self, client_id, project_id, path, task_id, days, worktree_id):
        self.authorize_project(client_id,project_id)
        if not isinstance(days,int) or isinstance(days,bool) or not 1<=days<=90:
            raise DomainError('Inspector window must be one to 90 days.')
        self.storage.validate_scope(project_id,task_id)
        if worktree_id:
            wt = self._workspace(client_id,worktree_id)
            path = normalize_remote_file(wt['worktree_path'],wt['platform'],path)
        else:
            path = relative_path(path)
        preview = self.context.resolve(project_id=project_id,task_id=task_id,file_path=path)
        cutoff = (datetime.utcnow()-timedelta(days=days)).isoformat()
        deliveries = []
        for row in self.storage.conn.execute('''SELECT d.*,s.agent_client,s.task_id FROM context_deliveries d
                JOIN agent_sessions s ON d.session_id=s.id JOIN remote_session_bindings b ON b.session_id=s.id
                WHERE b.client_id=? AND s.project_id=? AND d.file_path=? AND d.created_at>=?
                ORDER BY d.created_at DESC LIMIT 500''',(client_id,project_id,path,cutoff)):
            response = json.loads(row['response_json'])
            deliveries.append({'delivery_id':row['id'],'session_id':row['session_id'],'agent_name':row['agent_client'],
                'task_id':row['task_id'],'created_at':row['created_at'],'file_path':path,
                'rendered_markdown':response.get('rendered_markdown','')})
        return {'path':path,'task_id':task_id,'days':days,'rules':preview.long_term_rules+preview.short_term_rules,
                'deliveries':deliveries,'visibility':'authenticated_client_sessions_only','delivery_limit':500}


def create_remote_router(registry: RemoteRegistry):
    """Mount under the application's DomainError handler; does not expose enrollment."""
    from fastapi import APIRouter, Request
    from pydantic import BaseModel, ConfigDict, Field
    class RPCRequest(BaseModel):
        model_config = ConfigDict(extra='forbid')
        op: str = Field(min_length=1,max_length=80)
        args: dict = Field(default_factory=dict)
    router = APIRouter()

    @router.post('/api/client/rpc')
    def client_rpc(request: Request, body: RPCRequest):
        authorization = request.headers.get('authorization','')
        token = authorization[7:] if authorization[:7].lower()=='bearer ' else ''
        client = registry.authenticate(token)
        return {'result':registry.rpc(client['id'],body.op,body.args)}
    return router

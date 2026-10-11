"""Transport-authenticated identities shared by stdio and HTTP MCP.

Client credentials come from operator-controlled environment, never worktree files
or model arguments. The server does not persist bearer tokens or log them.
"""
import hmac
import json
import os

from mcp.server.mcpserver.exceptions import ToolError

from ...modules.workspaces import Actor


class Identities:
    def __init__(self, declarations: list[dict], environ=None):
        environ = os.environ if environ is None else environ
        self._entries = []
        for item in declarations:
            name = item.get('token_env', '')
            secret = environ.get(name, '')
            projects = item.get('project_ids')
            if (not name.startswith('CODENEURO_') or not name.endswith('_TOKEN')
                    or len(secret) < 24 or not isinstance(projects, list) or not projects
                    or not all(isinstance(project, str) and project for project in projects)
                    or not isinstance(item.get('actor_id'), str) or not item['actor_id']
                    or item.get('role', 'agent') not in ('agent', 'human')):
                raise ValueError('Every client needs a dedicated nonempty credential and project scope.')
            actor = Actor(item['actor_id'], frozenset(projects), item.get('role', 'agent'))
            self._entries.append((secret, actor))
        if not self._entries or len({secret for secret, _ in self._entries}) != len(self._entries):
            raise ValueError('At least one client and distinct secrets are required.')

    @classmethod
    def from_environment(cls):
        try:
            declarations = json.loads(os.environ['CODENEURO_CLIENTS'])
        except (KeyError, ValueError) as error:
            raise ValueError('Set CODENEURO_CLIENTS to operator-controlled client metadata.') from error
        if not isinstance(declarations, list):
            raise ValueError('CODENEURO_CLIENTS must contain a list.')
        return cls(declarations)

    def authenticate(self, token: str) -> Actor:
        match = None
        for secret, actor in self._entries:
            if hmac.compare_digest(secret, token):
                match = actor
        if match is None:
            raise ToolError('unauthorized: valid CodeNeuro bearer credential required')
        return match

    def for_stdio(self):
        # The stdio launcher is a trusted process, but its identity is still
        # derived from its credential rather than user-controlled tool params.
        return self.authenticate(os.environ.get('CODENEURO_TOKEN', ''))

    def for_http(self, ctx):
        request = getattr(getattr(ctx, 'request_context', None), 'request', None)
        if request is None:
            raise ToolError('unauthorized: HTTP request context required')
        authorization = request.headers.get('authorization', '')
        if authorization[:7].lower() != 'bearer ':
            raise ToolError('unauthorized: bearer credential required')
        return self.authenticate(authorization[7:])

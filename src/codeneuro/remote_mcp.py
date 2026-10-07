"""Authenticated streamable HTTP MCP surface for remote Agent clients.

The local stdio sidecar adds native file/test tools. This Hub-only surface
accepts project-scoped credentials on every request and never treats a remote
workstation path as a file visible on the Hub.
"""
import json
from typing import Optional
from mcp.server.mcpserver import Context, MCPServer
from .database import DomainError
from .remote import RemoteRegistry


def create_remote_mcp(registry: RemoteRegistry):
    server=MCPServer('CodeNeuro Hub', instructions=(
        'Authenticate with a project-scoped CodeNeuro client token. Register the actual '
        'workstation and task with codeneuro_start_session, then request scoped context '
        'before file work. Direct Hub MCP cannot read local workstation files; use the '
        'local CodeNeuro stdio sidecar for automatically contextualized read/edit/test. '
        'Feedback requires an actual delivery_id and an honest observed reason.'))

    def caller(ctx: Context):
        request=ctx.request_context.request
        if request is None:
            raise DomainError('A client bearer token is required.', 'unauthorized', 401)
        authorization=request.headers.get('authorization','')
        token=authorization[7:] if authorization[:7].lower()=='bearer ' else ''
        return registry.authenticate(token)['id']

    def call(ctx,op,args=None):
        return json.dumps(registry.rpc(caller(ctx),op,args or {}),ensure_ascii=False)

    @server.tool()
    def codeneuro_list_projects(ctx: Context) -> str:
        """List only projects authorized by this client token."""
        return call(ctx,'list_projects')

    @server.tool()
    def codeneuro_list_tasks(project_id: str,ctx: Context) -> str:
        """List real tasks in an authorized project."""
        return call(ctx,'list_tasks',{'project_id':project_id})

    @server.tool()
    def codeneuro_create_task(project_id: str,title: str,ctx: Context,description: str='') -> str:
        """Create a task in an authorized project before assigning its worktree."""
        return call(ctx,'create_task',{'project_id':project_id,'title':title,'description':description})

    @server.tool()
    def codeneuro_start_session(project_id: str,workspace_path: str,machine_name: str,
                                platform: str,ctx: Context,task_id: Optional[str]=None,
                                git_branch: str='',git_commit: Optional[str]=None,
                                repo_identity: Optional[str]=None,agent_client: str='Remote MCP',
                                debug: bool=False) -> str:
        """Register client-attested Windows/Linux/macOS worktree metadata without NAS file access."""
        args=dict(project_id=project_id,workspace_path=workspace_path,machine_name=machine_name,
                  platform=platform,git_branch=git_branch,task_id=task_id,agent_client=agent_client,
                  debug=debug)
        if git_commit:args['git_commit']=git_commit
        if repo_identity:args['repo_identity']=repo_identity
        return call(ctx,'start_session',args)

    @server.tool()
    def codeneuro_get_context(session_id: str,file_path: str,ctx: Context,
                              request_id: Optional[str]=None,max_chars: int=24000) -> str:
        """Deliver actual matched rules and a rating receipt for a client-owned session."""
        result=registry.rpc(caller(ctx),'context',dict(session_id=session_id,file_path=file_path,
                          request_id=request_id,max_chars=max_chars))
        return result['rendered_markdown']

    @server.tool()
    def codeneuro_rate_rule(session_id: str,delivery_id: str,rule_id: str,score: int,
                            ctx: Context,reason: str='') -> str:
        """Rate only a rule delivered to this owned debug session; 0 means known, 1 irrelevant."""
        return call(ctx,'feedback',dict(session_id=session_id,delivery_id=delivery_id,
                                        rule_id=rule_id,score=score,reason=reason))

    @server.tool()
    def codeneuro_report_issue(session_id: str,issue_type: str,title: str,description: str,
                               file_path: str,ctx: Context,related_rule_ids: Optional[list[str]]=None,
                               suggested_action: str='') -> str:
        """Submit an observed scoped issue for human review, not automatic approval."""
        return call(ctx,'issue',dict(session_id=session_id,issue_type=issue_type,title=title,
                                     description=description,file_path=file_path,
                                     related_rule_ids=related_rule_ids or [],suggested_action=suggested_action))

    @server.tool()
    def codeneuro_record_finding(session_id: str,target_path: str,text: str,
                                ctx: Context,priority: str='P1') -> str:
        """Record an observed task-scoped finding with client/session provenance."""
        return call(ctx,'finding',dict(session_id=session_id,target_path=target_path,text=text,priority=priority))

    @server.tool()
    def codeneuro_list_rules(session_id: str,ctx: Context) -> str:
        """List contracts and task rules visible to this owned session."""
        return call(ctx,'list_rules',{'session_id':session_id})

    @server.tool()
    def codeneuro_propose_contract(session_id: str,target_component: str,
                                  proposed_contract: str,justification: str,ctx: Context) -> str:
        """Propose a long-term contract for human approval; never self-activate it."""
        return call(ctx,'propose_contract',dict(session_id=session_id,target_component=target_component,
                                                proposed_contract=proposed_contract,justification=justification))

    @server.tool()
    def codeneuro_bind_task(session_id: str,expected_revision: int,ctx: Context,
                           task_id: Optional[str]=None) -> str:
        """Switch an owned session task only at a verified idle operation boundary."""
        return call(ctx,'bind_task',dict(session_id=session_id,task_id=task_id,
                                         expected_revision=expected_revision))

    @server.tool()
    def codeneuro_end_session(session_id: str,ctx: Context) -> str:
        """Close an owned session after useful work; this does not mark its task completed."""
        return call(ctx,'close_session',{'session_id':session_id})

    return server

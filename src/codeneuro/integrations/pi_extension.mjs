/** Pi 0.80 native interception and an actual stdio MCP client relay.
 * Sources: installed Pi docs/extensions.md and core/extensions/types.d.ts.
 * No project-trust override or model-provider mutation is installed.
 */
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';

export class McpRelay {
  constructor(python, workspace, hostSessionId, spawnChild = spawn) {
    this.pending = new Map(); this.counter = 0; this.stopped = false;
    this.child = spawnChild(python, ['-m', 'codeneuro.integrations.pi_mcp', '--workspace', workspace], {
      cwd: workspace, env: { ...process.env, CODENEURO_HOST_SESSION_ID: hostSessionId, CODENEURO_AGENT_CLIENT: 'Pi' },
      stdio: ['pipe', 'pipe', 'pipe'], shell: false,
    });
    this.ready = new Promise((resolve, reject) => {
      this.resolveReady = resolve; this.rejectReady = reject;
      this.startupTimer = setTimeout(() => { this.fail(new Error('CodeNeuro MCP startup timed out')); this.close(); }, 30000);
    });
    this.lines = createInterface({ input: this.child.stdout });
    this.lines.on('line', line => {
      let message;
      try { message = JSON.parse(line); } catch { this.fail(new Error('Invalid CodeNeuro relay JSON')); return; }
      if ('ready' in message) {
        clearTimeout(this.startupTimer);
        if (message.ready) this.resolveReady(message.tools); else this.fail(new Error(message.error));
      } else {
        const entry = this.pending.get(message.id);
        if (entry) {
          this.pending.delete(message.id); clearTimeout(entry.timer);
          message.error ? entry.reject(new Error(message.error)) : entry.resolve(message.result);
        }
      }
    });
    // Sidecar diagnostics are retained by its own logger; never leak env or raw
    // HTTP exception strings through extension stderr into a model tool result.
    this.child.stderr.on('data', () => {});
    this.child.on('error', error => this.fail(error));
    this.child.on('exit', () => this.fail(new Error('CodeNeuro MCP relay stopped')));
  }
  fail(error) {
    clearTimeout(this.startupTimer); this.rejectReady(error);
    for (const value of this.pending.values()) { clearTimeout(value.timer); value.reject(error); }
    this.pending.clear();
  }
  async call(name, args) {
    await this.ready;
    if (this.stopped) throw new Error('CodeNeuro relay is closed');
    const id = ++this.counter;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error('CodeNeuro MCP call timed out')); }, 180000);
      this.pending.set(id, { resolve, reject, timer });
      this.child.stdin.write(JSON.stringify({ id, method: 'tools/call', name, arguments: args }) + '\n');
    });
  }
  close() {
    if (this.stopped) return;
    this.stopped = true;
    if (this.child.stdin.writable) this.child.stdin.end(JSON.stringify({ method: 'close' }) + '\n');
    const timer = setTimeout(() => this.child.kill(), 3000); timer.unref();
  }
}

export function invokeNative(python, event, spawnChild = spawn) {
  return new Promise((resolve, reject) => {
    const child = spawnChild(python, ['-m', 'codeneuro.integrations.pi_hooks'], {
      cwd: event.cwd, env: process.env, stdio: ['pipe', 'pipe', 'pipe'], shell: false,
    });
    let output = '';
    const timer = setTimeout(() => { child.kill(); reject(new Error('CodeNeuro native hook timed out')); }, 180000);
    child.stdout.on('data', chunk => { output += chunk; if (output.length > 2000000) child.kill(); });
    child.stderr.on('data', () => {});
    child.on('error', error => { clearTimeout(timer); reject(error); });
    child.on('close', code => {
      clearTimeout(timer);
      try { if (code !== 0) throw new Error('CodeNeuro hook process failed'); resolve(JSON.parse(output)); }
      catch (error) { reject(error); }
    });
    child.stdin.end(JSON.stringify(event));
  });
}

export default function codeneuro(pi) {
  const python = process.env.CODENEURO_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
  const contexts = new Map();
  let relay;
  const nativeEvent = (event, ctx, hookEventName) => ({
    session_id: ctx.sessionManager.getSessionId(), cwd: ctx.cwd, hook_event_name: hookEventName,
    tool_name: event.toolName === 'bash' ? 'Bash' : event.toolName,
    tool_input: event.input, tool_use_id: event.toolCallId,
    // Pi's BashToolDetails has no exitCode; never pretend plain output is a
    // measured test result. Use the MCP command tool for recorded test execution.
    transcript_path: null,
  });
  pi.on('session_start', async (_event, ctx) => {
    relay = new McpRelay(python, ctx.cwd, ctx.sessionManager.getSessionId());
    try {
      for (const tool of await relay.ready) {
        const name = 'codeneuro_' + tool.name;
        pi.registerTool({
          name, label: 'CodeNeuro: ' + tool.name, description: tool.description || tool.name,
          promptSnippet: 'CodeNeuro governed workspace tool: ' + tool.name,
          parameters: tool.inputSchema,
          async execute(_id, args) {
            const result = await relay.call(tool.name, args);
            if (result.isError) throw new Error(result.content.filter(c => c.type === 'text').map(c => c.text).join('\n'));
            const content = result.content.filter(c => c.type === 'text' || c.type === 'image');
            return { content: content.length ? content : [{ type: 'text', text: JSON.stringify(result.structuredContent ?? result) }],
                     details: result.structuredContent ?? {} };
          },
        });
      }
    } catch (error) {
      ctx.ui?.notify?.(error.message, 'error');
    }
  });
  pi.on('tool_call', async (event, ctx) => {
    if (event.toolName.startsWith('codeneuro_')) return;
    if (!['read', 'edit', 'write', 'bash'].includes(event.toolName)) return;
    try {
      const response = await invokeNative(python, nativeEvent(event, ctx, 'PreToolUse'));
      const hook = response.hookSpecificOutput || {};
      if (hook.permissionDecision === 'deny') return { block: true, reason: hook.permissionDecisionReason };
      if (hook.additionalContext) contexts.set(event.toolCallId, hook.additionalContext);
    } catch (error) {
      return { block: true, reason: 'CodeNeuro native hook unavailable: ' + error.message };
    }
  });
  pi.on('tool_result', async (event, ctx) => {
    if (event.toolName.startsWith('codeneuro_')) return;
    if (!['read', 'edit', 'write', 'bash'].includes(event.toolName)) return;
    const context = contexts.get(event.toolCallId);
    contexts.delete(event.toolCallId);
    let post = '';
    try {
      const response = await invokeNative(python, { ...nativeEvent(event, ctx, 'PostToolUse'), tool_failed: !!event.isError });
      post = response.hookSpecificOutput?.additionalContext || response.systemMessage || '';
    } catch (error) { post = 'CodeNeuro could not close the operation receipt: ' + error.message; }
    if (context || post) return { content: [...event.content, { type: 'text', text: '\n' + [context, post].filter(Boolean).join('\n') }] };
  });
  pi.on('session_shutdown', async (_event, ctx) => {
    try { await invokeNative(python, { session_id: ctx.sessionManager.getSessionId(), cwd: ctx.cwd, hook_event_name: 'SessionEnd' }); }
    finally { relay?.close(); contexts.clear(); }
  });
}

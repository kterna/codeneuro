"""Translate Pi native events into the shared scoped context/preflight bridge."""
import json
from pathlib import Path
import sys

from .codex_hooks import HookState, find_config, handle_event, _output


def main():
    state = None
    event = {}
    try:
        raw = sys.stdin.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError('Input limit exceeded')
        event = json.loads(raw)
        root = Path(event['cwd']).resolve()
        from codeneuro.client import create_native_bridge
        bridge = create_native_bridge(config_path=find_config(root), workspace=root,
                                      host_session_id=event['session_id'], agent_client='Pi')
        state = HookState(root)
        result = handle_event(event, workspace=root, bridge=bridge, state=state)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        message = 'CodeNeuro Pi native bridge failed (' + type(exc).__name__ + '). Check the Hub/client configuration.'
        print(json.dumps(_output('PreToolUse', deny=message) if event.get('hook_event_name') == 'PreToolUse'
                         else {'systemMessage': message}))
        return 0
    finally:
        if state:
            state.close()


if __name__ == '__main__':
    raise SystemExit(main())

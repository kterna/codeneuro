"""Explicit environment-configured provider boundary. No heuristic success fallback."""
from __future__ import annotations

import json
import os
from urllib.parse import urlparse

import httpx

from .database import DomainError


class CompatibleProvider:
    def __init__(self, *, client=None):
        self.client = client

    def configuration(self):
        base = os.getenv('CODENEURO_LLM_BASE_URL', '').rstrip('/')
        model = os.getenv('CODENEURO_LLM_MODEL', '')
        key = os.getenv('CODENEURO_LLM_API_KEY', '')
        style = os.getenv('CODENEURO_LLM_API_STYLE', 'chat_completions')
        if not base or not model or not key:
            raise DomainError('Configure CODENEURO_LLM_BASE_URL, CODENEURO_LLM_MODEL and CODENEURO_LLM_API_KEY on the Hub.',
                              'provider_unavailable', 503)
        parsed = urlparse(base)
        if parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise DomainError('Provider base URL must be an HTTP(S) origin/path without embedded credentials or query.', 'provider_unavailable', 503)
        if style not in {'chat_completions', 'responses'}:
            raise DomainError('CODENEURO_LLM_API_STYLE must be chat_completions or responses.', 'provider_unavailable', 503)
        try:
            timeout = min(300, max(5, float(os.getenv('CODENEURO_LLM_TIMEOUT', '120'))))
        except ValueError:
            raise DomainError('Invalid CODENEURO_LLM_TIMEOUT.', 'provider_unavailable', 503) from None
        return base, model, key, style, timeout

    def complete(self, *, system: str, payload: dict, request_id: str) -> dict:
        base, model, key, style, timeout = self.configuration()
        user = json.dumps(payload, ensure_ascii=False)
        messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]
        if style == 'responses':
            body = dict(model=model, input=messages, stream=False, store=False)
            endpoint = '/responses'
        else:
            body = dict(model=model, messages=messages, stream=False)
            endpoint = '/chat/completions'
        own = self.client is None
        client = self.client or httpx.Client(timeout=timeout, follow_redirects=False)
        try:
            response = client.post(base + endpoint, json=body, timeout=timeout,
                                   headers={'Authorization': f'Bearer {key}', 'Idempotency-Key': request_id})
            if response.status_code >= 400:
                # Never copy provider bodies or HTTP exception repr: either can echo a credential.
                raise DomainError(f'Provider returned HTTP {response.status_code}. Review provider configuration or retry.',
                                  'provider_unavailable', 502)
            if len(response.content) > 4_000_000:
                raise DomainError('Provider response exceeds the 4 MB limit.', 'provider_response_invalid', 502)
            data = response.json()
            if style == 'responses':
                if data.get('status') in {'failed', 'cancelled', 'incomplete'}:
                    raise DomainError('Provider did not complete the response.', 'provider_response_invalid', 502)
                parts = [part.get('text', '') for item in data.get('output', []) if item.get('type') == 'message'
                         for part in item.get('content', []) if part.get('type') == 'output_text']
                content = ''.join(parts) or data.get('output_text', '')
            else:
                choice = data['choices'][0]
                if choice.get('finish_reason') not in {None, 'stop'}:
                    raise DomainError('Provider response was truncated or did not finish normally.', 'provider_response_invalid', 502)
                content = choice['message'].get('content', '')
            if not isinstance(content, str):
                raise ValueError('Expected text')
            content = content.strip()
            if content.startswith('```') and content.endswith('```'):
                content = content.split('\n', 1)[-1].rsplit('```', 1)[0].strip()
            result = json.loads(content)
            if not isinstance(result, dict):
                raise ValueError('Expected object')
            return {'data': result, 'provider': {'model': model, 'api_style': style},
                    'usage': {k: v for k, v in (data.get('usage') or {}).items() if isinstance(v, (int, float))}}
        except DomainError:
            raise
        except httpx.TimeoutException:
            raise DomainError('Provider request timed out; the job may be retried.', 'provider_unavailable', 504) from None
        except httpx.HTTPError:
            raise DomainError('Could not connect to the configured provider.', 'provider_unavailable', 502) from None
        except (ValueError, KeyError, IndexError, TypeError):
            raise DomainError('Provider returned an invalid structured JSON response.', 'provider_response_invalid', 502) from None
        finally:
            if own:
                client.close()

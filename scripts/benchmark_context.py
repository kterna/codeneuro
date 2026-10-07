#!/usr/bin/env python3
"""Measure actual concurrent HTTP context requests against an isolated fixture.

No production URL or database option exists. All sessions/rules are explicitly
synthetic and live in a temporary directory removed after the server stops.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import secrets
import socket
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time

import httpx
from fastapi import Request


def percentile(values, percent):
    """Nearest-rank percentile, explicitly retained in the output schema."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * percent / 100) - 1)]


def resources():
    peak_rss = None
    try:
        import resource
        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak_rss = value if sys.platform == 'darwin' else value * 1024
    except (ImportError, AttributeError):
        pass
    return {'cpu_seconds': time.process_time(), 'peak_rss_bytes': peak_rss}


def serve_fixture(database, ready_file):
    import hmac
    import uvicorn
    from fastapi.responses import JSONResponse
    from codeneuro.api import create_app

    app = create_app(db_path=str(database))
    counters = {'active': 0, 'peak_active': 0, 'requests_seen': 0}

    @app.middleware('http')
    async def measure_inflight(request: Request, call_next):
        measured = request.url.path == '/api/agent/context'
        if measured:
            counters['active'] += 1
            counters['requests_seen'] += 1
            counters['peak_active'] = max(counters['peak_active'], counters['active'])
        try:
            return await call_next(request)
        finally:
            if measured:
                counters['active'] -= 1

    @app.get('/__benchmark/metrics')
    def benchmark_metrics(request: Request):
        supplied = request.headers.get('authorization', '').removeprefix('Bearer ')
        if not hmac.compare_digest(supplied, os.environ['CODENEURO_API_TOKEN']):
            return JSONResponse({'error': 'unauthorized'}, status_code=401)
        return {**counters, **resources()}

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(('127.0.0.1', 0))
    listener.listen(2048)
    host, port = listener.getsockname()
    Path(ready_file).write_text(json.dumps({'host': host, 'port': port}), encoding='utf-8')
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, access_log=False, log_level='error'))
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()


def seed_fixture(directory, rule_count, concurrency):
    from codeneuro.models import Lifecycle, Priority, Project, Rule, Task
    from codeneuro.service import ContextService
    from codeneuro.storage import Storage

    workspace = directory / 'workspace'
    workspace.mkdir()
    database = directory / 'fixture.db'
    store = Storage(str(database))
    expected = {f'src/module_{i}/file.py': {'bench_rule_0'} for i in range(50)}
    try:
        with store.transaction():
            store.create_project(Project(id='bench_project', name='SYNTHETIC benchmark', root_paths=[str(workspace)]))
            for task_id in ('bench_task_a', 'bench_task_b'):
                store.create_task(Task(id=task_id, project_id='bench_project', title='SYNTHETIC ' + task_id))
            for index in range(rule_count):
                task_id = None if index == 0 or index % 3 else 'bench_task_a'
                if index and index % 4 == 0:
                    task_id = 'bench_task_b'
                rid = f'bench_rule_{index}'
                scope = '**' if index == 0 else f'src/module_{index % 50}/**'
                store.create_rule(Rule(id=rid, project_id='bench_project', task_id=task_id,
                    lifecycle=Lifecycle.SHORT_TERM if task_id else Lifecycle.LONG_TERM,
                    priority=Priority.P0 if index == 0 else Priority.P1,
                    title=f'SYNTHETIC bounded rule {index}', scope_patterns=[scope],
                    content_points=[f'Synthetic fixture clause {index}; no real coding evidence.']))
                if index and task_id != 'bench_task_b':
                    expected[f'src/module_{index % 50}/file.py'].add(rid)
        context = ContextService(store)
        sessions = [context.start_session('bench_project', str(workspace), 'bench_task_a',
            agent_client='SYNTHETIC HTTP benchmark', debug=False)['id'] for _ in range(concurrency)]
        return database, sessions, expected
    finally:
        store.close()


async def requests(base_url, token, sessions, expected, count, concurrency, timeout_seconds):
    headers = {'Authorization': 'Bearer ' + token}
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)
    semaphore = asyncio.Semaphore(concurrency)
    start_gate = asyncio.Event()
    active, peak, latencies, sizes, errors, receipts, statuses = 0, 0, [], [], [], set(), Counter()
    paths = sorted(expected)
    async with httpx.AsyncClient(base_url=base_url, headers=headers, limits=limits,
                                 timeout=timeout_seconds, trust_env=False) as client:
        before = (await client.get('/__benchmark/metrics')).json()
        async def one(index):
            nonlocal active, peak
            await start_gate.wait()
            async with semaphore:
                active += 1
                peak = max(peak, active)
                started = time.perf_counter()
                path = paths[index % len(paths)]
                try:
                    response = await client.post('/api/agent/context', json={
                        'session_id': sessions[index % len(sessions)], 'file_path': path,
                        'request_id': f'benchmark-request-{index}', 'max_chars': 200000})
                    elapsed = (time.perf_counter() - started) * 1000
                    latencies.append(elapsed)
                    sizes.append(len(response.content))
                    statuses[str(response.status_code)] += 1
                    if response.status_code != 200:
                        errors.append({'request': index, 'kind': 'http_status', 'status': response.status_code})
                        return
                    payload = response.json()
                    actual = {r['id'] for r in payload['long_term_rules'] + payload['short_term_rules']}
                    if actual != expected[path] or payload['project_id'] != 'bench_project' or payload['task_id'] != 'bench_task_a':
                        errors.append({'request': index, 'kind': 'scope_or_rule_mismatch',
                                       'missing': sorted(expected[path] - actual), 'unexpected': sorted(actual - expected[path])})
                    receipt = payload.get('delivery_id')
                    if not receipt or receipt in receipts:
                        errors.append({'request': index, 'kind': 'missing_or_duplicate_receipt'})
                    receipts.add(receipt)
                except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                    elapsed = (time.perf_counter() - started) * 1000
                    if not isinstance(exc, (ValueError, KeyError, TypeError)):
                        latencies.append(elapsed)
                    errors.append({'request': index, 'kind': type(exc).__name__})
                finally:
                    active -= 1
        tasks = [asyncio.create_task(one(i)) for i in range(count)]
        started = time.perf_counter()
        start_gate.set()
        await asyncio.gather(*tasks)
        duration = time.perf_counter() - started
        after = (await client.get('/__benchmark/metrics')).json()
    return {'duration_seconds': duration, 'requests_completed': sum(statuses.values()),
            'requests_succeeded': statuses.get('200', 0), 'request_errors': len(errors), 'http_statuses': dict(statuses),
            'throughput_requests_per_second': count / duration,
            'successful_throughput_per_second': statuses.get('200', 0) / duration,
            'latency_ms': {**{f'p{p}': percentile(latencies, p) for p in (50, 90, 95, 99)},
                           'min': min(latencies) if latencies else None, 'max': max(latencies) if latencies else None,
                           'mean': statistics.mean(latencies) if latencies else None},
            'percentile_method': 'nearest_rank', 'client_peak_inflight': peak,
            'server_peak_inflight': after['peak_active'], 'server_requests_seen': after['requests_seen'],
            'mean_response_bytes': statistics.mean(sizes) if sizes else None,
            'unique_receipts_observed': len(receipts)}, {
            'server_cpu_seconds_during_requests': after['cpu_seconds'] - before['cpu_seconds'],
            'server_peak_rss_bytes': after['peak_rss_bytes']}, errors, latencies


def environment_metadata():
    commit, dirty = None, None
    try:
        result = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            commit = result.stdout.strip()
            status = subprocess.run(['git', 'status', '--porcelain'], capture_output=True, text=True, timeout=5)
            dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        pass
    memory_bytes, cpu_model = None, platform.processor() or None
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            if line.startswith('MemTotal:'):
                memory_bytes = int(line.split()[1]) * 1024
        for line in Path('/proc/cpuinfo').read_text().splitlines():
            if line.startswith('model name'):
                cpu_model = line.split(':', 1)[1].strip()
                break
    except (OSError, ValueError):
        pass
    return {'python': platform.python_version(), 'os': platform.system(), 'os_release': platform.release(),
            'architecture': platform.machine(), 'cpu_count': os.cpu_count(), 'cpu_model': cpu_model,
            'memory_bytes': memory_bytes, 'sqlite': sqlite3.sqlite_version, 'git_commit': commit,
            'git_dirty': dirty, 'benchmark_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'transport': 'HTTP over loopback TCP', 'database': 'temporary SQLite WAL fixture'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rules', type=int, default=1000)
    parser.add_argument('--requests', type=int, default=1000)
    parser.add_argument('--concurrency', type=int, default=100)
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--serve-fixture', nargs=2, metavar=('DATABASE', 'READY_FILE'), help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.serve_fixture:
        if os.environ.get('CODENEURO_BENCHMARK_CHILD') != '1':
            parser.error('Fixture server is an internal child mode.')
        serve_fixture(*args.serve_fixture)
        return 0
    if not (1 <= args.rules <= 100000 and 1 <= args.concurrency <= min(1000, args.requests) and 1 <= args.requests <= 100000 and 1 <= args.timeout <= 600):
        parser.error('Require rules/requests 1..100000, concurrency 1..min(1000, requests), timeout 1..600.')
    metadata = environment_metadata()
    with tempfile.TemporaryDirectory(prefix='codeneuro-benchmark-') as temporary:
        directory = Path(temporary)
        database, sessions, expected = seed_fixture(directory, args.rules, args.concurrency)
        ready = directory / 'ready.json'
        token = secrets.token_urlsafe(32)
        child_env = {k: v for k, v in os.environ.items() if not k.startswith('CODENEURO_')}
        child_env.update(CODENEURO_API_TOKEN=token, CODENEURO_BENCHMARK_CHILD='1')
        with (directory / 'server.log').open('w', encoding='utf-8') as logs:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--serve-fixture', str(database), str(ready)],
                                       env=child_env, stdout=logs, stderr=logs)
            try:
                deadline = time.monotonic() + 30
                base_url = None
                with httpx.Client(timeout=1, trust_env=False, headers={'Authorization': 'Bearer ' + token}) as probe:
                    while time.monotonic() < deadline:
                        if process.poll() is not None:
                            raise RuntimeError('Isolated fixture server exited during startup.')
                        if ready.exists():
                            try:
                                address = json.loads(ready.read_text(encoding='utf-8'))
                                candidate = f'http://127.0.0.1:{int(address["port"])}'
                                if probe.get(candidate + '/__benchmark/metrics').status_code == 200:
                                    base_url = candidate
                                    break
                            except (httpx.HTTPError, ValueError):
                                pass
                        time.sleep(0.05)  # Observe the specific live child; not part of measured workload.
                if not base_url:
                    raise RuntimeError('Isolated fixture server did not become ready within 30 seconds.')
                before_cpu = time.process_time()
                metrics, resource_metrics, errors, latencies = asyncio.run(requests(
                    base_url, token, sessions, expected, args.requests, args.concurrency, args.timeout))
                resource_metrics['client_cpu_seconds_during_requests'] = time.process_time() - before_cpu
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
        with sqlite3.connect(database) as connection:
            receipts = connection.execute('SELECT COUNT(*) FROM context_deliveries').fetchone()[0]
            integrity = connection.execute('PRAGMA integrity_check').fetchone()[0]
            foreign_keys = len(connection.execute('PRAGMA foreign_key_check').fetchall())
        validation = {'durable_receipts': receipts, 'expected_receipts': args.requests,
                      'integrity_check': integrity, 'foreign_key_violations': foreign_keys,
                      'rule_and_task_isolation_checked_on_every_response': True,
                      'fixture_database_bytes': database.stat().st_size}
        validation['passed'] = not errors and receipts == args.requests and integrity == 'ok' and foreign_keys == 0
        report = {'schema_version': 1, 'kind': 'synthetic_isolated_http_benchmark',
                  'created_at': datetime.now(timezone.utc).isoformat(), 'environment': metadata,
                  'workload': {'rules': args.rules, 'requests': args.requests, 'configured_concurrency': args.concurrency,
                               'sessions': len(sessions), 'tasks': 2, 'projects': 1, 'scope_buckets': 50,
                               'matched_rules_per_path_min': min(map(len, expected.values())),
                               'matched_rules_per_path_max': max(map(len, expected.values())),
                               'debug': False, 'context_max_chars': 200000, 'synthetic': True},
                  'metrics': metrics, 'resources': resource_metrics, 'validation': validation,
                  'errors': errors, 'latency_samples_ms': latencies}
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + '\n', encoding='utf-8')
        print(json.dumps({'output': str(args.output), 'passed': validation['passed'],
                          'p95_ms': metrics['latency_ms']['p95'], 'throughput': metrics['throughput_requests_per_second']}))
    else:
        print(encoded)
    return 0 if validation['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

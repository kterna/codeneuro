"""Requirement/Task browser acceptance in browser_smoke's disposable environment."""
import json


def run_task_flow(page, fetch, base_url, wait):
    prefix = base_url + '/api/projects/browser-project'
    def get_requirement(identity): return fetch(prefix + '/requirements/' + identity)
    def get_task(identity): return fetch(prefix + '/tasks/' + identity)
    def api(path, method, body):
        return page.js('(async()=>{const r=await fetch(' + json.dumps(path) + ',{method:' + json.dumps(method)
            + ',headers:{"Content-Type":"application/json"},body:JSON.stringify(' + json.dumps(body) + ')});'
            'if(!r.ok)throw Error(await r.text());return r.json()})()')
    def escape():
        page.cdp('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'Escape', 'code': 'Escape', 'windowsVirtualKeyCode': 27})
        page.cdp('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'Escape', 'code': 'Escape', 'windowsVirtualKeyCode': 27})
    def close_task():
        page.js("document.querySelector('.task-detail .close-btn').click()")
        page.until("!document.querySelector('.task-detail')")
    def action(label, submit, scope, summary=None):
        page.click(label, scope)
        page.until("!!document.querySelector('.task-action form')")
        if summary:
            page.field('验证方式与结果' if scope == '.task-detail' else '整体验收结论', summary, '.task-action')
        page.field('操作原因', 'Explicit synthetic browser action', '.task-action')
        page.click(submit, '.task-action')
        page.until("!document.querySelector('.task-action')")
    def create_requirement(title):
        page.js("document.querySelector('.task-workspace > details').open=true")
        page.field('需求名称', title, '.task-workspace > details')
        page.field('整体目标', '整体目标：分别开发并验证两个子任务。', '.task-workspace > details')
        page.field('整体验收要求', '两个任务分别通过后确认整体结果。', '.task-workspace > details')
        page.click('创建需求', '.task-workspace > details')
        page.until("document.querySelector('.requirement-detail h2')?.textContent === " + json.dumps(title))
        return next(item for item in fetch(prefix + '/requirements')['items'] if item['title'] == title)['id']

    page.click('需求与任务看板', '#navigation')
    page.until("!!document.querySelector('.task-workspace')")
    parent = create_requirement('Browser 整体需求')
    for title in ('子任务甲', '子任务乙'):
        page.js("document.querySelector('.new-task').open=true")
        page.field('任务名称', title, '.new-task')
        page.field('实现范围', title + '的独立实现范围', '.new-task')
        page.field('验证要求', title + '的独立验证要求', '.new-task')
        page.click('创建子任务', '.new-task')
        page.until("[...document.querySelectorAll('.tasks-table button')].some(b=>b.textContent === " + json.dumps(title) + ')')
    tasks = fetch(prefix + '/requirements/' + parent + '/tasks')['items']
    first = next(item['id'] for item in tasks if item['title'] == '子任务甲')
    second = next(item['id'] for item in tasks if item['title'] == '子任务乙')
    assert get_requirement(parent)['progress'] == {'total': 2, 'completed': 0}

    page.click('子任务甲', '.tasks-table')
    page.until("!!document.querySelector('.task-detail')")
    action('归档', '归档任务', '.task-detail')
    assert get_task(first)['archived_at'] and get_requirement(parent)['status'] == 'active'
    action('恢复归档', '恢复归档任务', '.task-detail')
    action('开发完成，提交验证', '提交验证', '.task-detail')
    action('验证通过', '确认子任务验证通过', '.task-detail', '甲已独立验证通过')
    assert get_requirement(parent)['progress'] == {'total': 2, 'completed': 1}
    assert get_requirement(parent)['status'] == 'active'

    # Nested history has its own keyboard focus; Escape closes only the top drawer.
    page.click('版本历史', '.task-detail')
    page.until("!!document.querySelector('.resource-history') && document.querySelector('.resource-history').contains(document.activeElement)")
    page.cdp('Input.dispatchKeyEvent', {'type': 'keyDown', 'key': 'Tab', 'code': 'Tab', 'windowsVirtualKeyCode': 9, 'modifiers': 8})
    page.cdp('Input.dispatchKeyEvent', {'type': 'keyUp', 'key': 'Tab', 'code': 'Tab', 'windowsVirtualKeyCode': 9})
    assert page.js("document.querySelector('.resource-history').contains(document.activeElement)")
    escape()
    page.until("!document.querySelector('.resource-history') && !!document.querySelector('.task-detail')")
    assert page.js("document.querySelector('.task-detail').contains(document.activeElement)")
    close_task()

    page.click('子任务乙', '.tasks-table')
    page.until("!!document.querySelector('.task-detail')")
    action('暂停', '暂停任务', '.task-detail')
    assert get_task(second)['status'] == 'paused'
    action('恢复', '恢复任务', '.task-detail')
    assert get_task(second)['status'] == 'active'
    page.click('修订任务', '.task-detail')
    page.until("!!document.querySelector('.task-action form')")
    current = get_task(second)
    api(prefix + '/tasks/' + second, 'PATCH', {'expected_version': current['version'],
        'changes': {'title': '子任务乙已由另一位 Agent 修订'}, 'reason': 'Synthetic concurrent writer'})
    page.field('操作原因', 'Attempt a stale update', '.task-action')
    page.click('修订任务', '.task-action')
    page.until("document.querySelector('.task-action [role=alert]')?.textContent.includes('stale')")
    assert get_task(second)['title'] == '子任务乙已由另一位 Agent 修订'
    escape()
    page.until("!document.querySelector('.task-action')")
    page.js("document.querySelector('#refresh').click()")
    page.until("document.querySelector('.task-detail h3')?.textContent === '子任务乙已由另一位 Agent 修订'")
    action('开发完成，提交验证', '提交验证', '.task-detail')
    action('验证通过', '确认子任务验证通过', '.task-detail', '乙已独立验证通过')
    assert get_requirement(parent)['status'] == 'accepting'
    close_task()
    action('确认整体验收通过', '确认整体验收通过', '.requirement-detail', '用户明确确认两项整体结果通过')
    assert get_requirement(parent)['status'] == 'completed'
    assert get_requirement(parent)['completion_summary'] == '用户明确确认两项整体结果通过'
    action('归档', '归档需求', '.requirement-detail')
    action('恢复归档', '恢复归档需求', '.requirement-detail')
    assert get_requirement(parent)['status'] == 'completed'
    action('重开需求', '重开需求', '.requirement-detail')
    page.click('子任务甲', '.tasks-table')
    page.until("!!document.querySelector('.task-detail')")
    action('退回开发', '退回开发', '.task-detail')
    assert get_requirement(parent)['status'] == 'active'
    action('删除', '删除子任务', '.task-detail')
    page.until("!document.querySelector('.task-detail')")
    assert get_task(first)['deleted_at'] and get_task(first)['status'] == 'active'

    empty = create_requirement('Browser 空需求删除')
    assert get_requirement(empty)['status'] == 'active'
    action('删除', '删除需求', '.requirement-detail')
    assert get_requirement(empty)['deleted_at']

    # Seed enough actual disposable records to exercise both paged lists.
    for index in range(22):
        api(prefix + '/requirements', 'POST', {'changes': {'title': '分页需求' + str(index), 'text': 'Synthetic pagination goal'}})
        api(prefix + '/tasks', 'POST', {'requirement_id': parent, 'changes': {'title': '分页子任务' + str(index)}})
    page.click('刷新', '.requirement-list')
    page.until("document.querySelectorAll('.requirement-item').length === 20")
    page.click('加载更多需求', '.requirement-list')
    page.until("document.querySelectorAll('.requirement-item').length === 23")
    page.js("[...document.querySelectorAll('.requirement-item')].find(b=>b.textContent.includes('Browser 整体需求')).click()")
    page.until("document.querySelectorAll('.tasks-table tbody tr').length === 20")
    page.click('加载更多子任务', '.requirement-detail')
    page.until("document.querySelectorAll('.tasks-table tbody tr').length === 23")
    assert page.js("new Set([...document.querySelectorAll('.tasks-table button')].map(b=>b.textContent)).size") == 23

    page.cdp('Emulation.setDeviceMetricsOverride', {'width': 390, 'height': 844, 'deviceScaleFactor': 1, 'mobile': False})
    page.until("window.innerWidth === 390")
    assert page.js("document.documentElement.scrollWidth <= window.innerWidth"), 'Horizontal overflow in the Task workspace'
    page.cdp('Emulation.setDeviceMetricsOverride', {'width': 1280, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False})

    # Switching project while a Requirement request is pending must abort the old view.
    api(base_url + '/api/projects', 'POST', {'id': 'browser-other', 'name': 'Other isolated project'})
    page.js("document.querySelector('#refresh').click()")
    page.until("!!document.querySelector('#project option[value=browser-other]')")
    page.js("(()=>{const saved=window.fetch;window.originalFetch=saved;window.pendingScopeReads=0;"
            "window.fetch=async function(input,init){"
            "if(!String(input).includes('/requirements/') || (init?.method && init.method!=='GET')) return saved(input,init);"
            "window.pendingScopeReads++;try{await new Promise(resolve=>setTimeout(resolve,300));return await saved(input,init)}"
            "finally{window.pendingScopeReads--}}})()")
    page.js("(()=>{document.querySelector('.requirement-item').click();const p=document.querySelector('#project');"
            "p.value='browser-other';p.dispatchEvent(new Event('change',{bubbles:true}))})()")
    page.until("document.querySelector('#project')?.value === 'browser-other' && document.querySelector('.requirement-list')?.textContent.includes('尚无需求')")
    page.until('window.pendingScopeReads === 0')
    assert page.js("document.querySelectorAll('.tasks-table tbody tr').length") == 0
    page.js("(()=>{window.fetch=window.originalFetch;delete window.originalFetch;const p=document.querySelector('#project');"
            "p.value='browser-project';p.dispatchEvent(new Event('change',{bubbles:true}))})()")
    page.until("document.querySelectorAll('.requirement-item').length === 20")
    return ['requirement_child_task_verification_acceptance', 'archive_restore_reopen_delete',
            'nested_drawer_keyboard_focus', 'stale_revision_rejected', 'requirement_and_task_pagination',
            'responsive_task_workspace', 'project_switch_during_request']

"""V2 workbench scenarios for browser_smoke.py's disposable environment only."""
import json


def seed_knowledge(database):
    """Explicit synthetic fixtures, not a production import or fabricated test evidence."""
    from codeneuro.adapters.sqlite.uow import SqliteUnitOfWork
    from codeneuro.modules.knowledge import Priority, Rule
    from codeneuro.modules.workspaces import Actor
    from codeneuro.workflows.product import Product

    uow = SqliteUnitOfWork(str(database))
    try:
        product = Product(uow)
        owner, agent = Actor('browser-owner', 'human'), Actor('browser-fixture')
        task = product.workspaces.create_task(agent, 'browser-project', 'Browser Topic fixture')
        session = product.workspaces.start_session(agent, 'browser-project', '/synthetic/worktree', task.id)
        product.knowledge.create_rule(owner, 'browser-project', 'Browser P3 guideline',
            ('Synthetic guideline for the preview',), ('frontend/**',), Priority.P3,
            topics=('frontend-layout',), validation_spec={'kind': 'review', 'basis': 'Explicit synthetic browser fixture'})
        finding = product.context.record_finding(agent, session.id, None,
            'Browser finding awaiting review', topics=('finding-only',))
        # Reproduce an unclassified migrated row. Normal creation intentionally forbids this.
        with uow.write() as tx:
            tx.knowledge.create_rule(Rule('browser-legacy', 'browser-project', None,
                'Browser legacy redline', ('Synthetic loss-prevention policy',), ('frontend/**',),
                Priority.P0, (), 1, 'active'))
        return finding.id
    finally:
        uow.dispose()


def run_topics_flow(database, page, fetch, base_url, wait):
    prefix = base_url + '/api/projects/browser-project'
    panel = '.topics-panel'
    def topic(key):
        return fetch(prefix + '/topics/' + key + '?include_usage=true')
    def ledger():
        return fetch(prefix + '/ledger')
    def finding():
        return next(item for item in ledger()['findings'] if item['id'] == finding_id)
    def create(key, name):
        page.click('新建主题', panel)
        page.until("!!document.querySelector('.topic-form') && !document.querySelector('.topics-empty-selection')")
        page.field('稳定 key', key, panel)
        page.field('显示名称', name, panel)
        page.field('业务边界', 'Synthetic browser topic boundary: ' + key, panel)
        page.field('操作理由', 'Explicit browser fixture registration', panel)
        page.click('创建主题', panel)
        wait(lambda: topic(key)['status'] == 'active')
        page.until("!!document.querySelector('.topics-empty-selection') && !document.querySelector('.topic-form')")
    def inspect(key):
        page.click('· ' + key, panel)
        page.until(f"document.querySelector('.topic-form input')?.value === {json.dumps(key)} && document.querySelector('.topic-form input').disabled")
        assert not page.js("!!document.querySelector('.topics-empty-selection')")
    def navigate(label, selector):
        page.click(label, '#navigation')
        page.until('!!document.querySelector(' + json.dumps(selector) + ')')

    navigate('项目设置与管理', panel)
    page.until("!!document.querySelector('.topics-empty-selection') && !document.querySelector('.topic-form')")
    create('frontend-layout', 'Frontend layout')
    inspect('frontend-layout')
    page.field('显示名称', 'Frontend layout renamed', panel)
    page.field('操作理由', 'Display name adjustment', panel)
    page.click('保存修改', panel)
    wait(lambda: topic('frontend-layout')['name'] == 'Frontend layout renamed')
    assert topic('frontend-layout')['version'] == 2

    create('unused-topic', 'Unused')
    inspect('unused-topic')
    page.field('操作理由', 'Delete unused topic explicitly', panel)
    page.click('删除无在用引用的主题', panel)
    wait(lambda: topic('unused-topic')['status'] == 'deleted')
    page.until("!!document.querySelector('.topics-empty-selection') && !document.querySelector('.topic-form')")
    # Reusing a tombstoned key must surface a real API conflict and retain the input.
    page.click('新建主题', panel)
    page.field('稳定 key', 'unused-topic', panel)
    page.field('显示名称', 'Must not replace history', panel)
    page.field('业务边界', 'Not a new identity', panel)
    page.field('操作理由', 'Verify rejected reuse', panel)
    page.click('创建主题', panel)
    page.until("document.querySelector('.topics-panel [role=alert]')?.textContent.includes('reserved')")
    assert page.js("document.querySelector('.topic-form input').value") == 'unused-topic'
    assert topic('unused-topic')['status'] == 'deleted'
    create('finding-only', 'Finding boundary')

    finding_id = seed_knowledge(database)
    page.js("document.querySelector('#refresh').click()")
    page.until("document.querySelector('.topics-panel').innerText.includes('规则 1 条')")
    page.click('查询', panel)
    inspect('frontend-layout')
    page.until("document.querySelector('.topic-form textarea')?.readOnly")
    assert page.js("[...document.querySelectorAll('.topics-panel button')].find(b=>b.textContent.includes('删除无在用引用')).disabled")
    assert page.js("[...document.querySelectorAll('.topics-panel button')].find(b=>b.textContent.includes('启用主题查询')).disabled")
    assert topic('frontend-layout')['definition_locked']

    navigate('项目规则库', '.github-rules-table')
    page.until("[...document.querySelectorAll('.rule-title-text')].some(e=>e.textContent==='Browser legacy redline')")
    page.js("[...document.querySelectorAll('.rule-title-text')].find(e=>e.textContent==='Browser legacy redline').closest('tr').click()")
    page.until("!!document.querySelector('.governance-panel input')")
    page.field('已登记主题 key', 'frontend-layout', '.governance-panel')
    page.field('真实检索路径', '', '.governance-panel')
    page.field('P0 损害与适用边界', 'Synthetic irreversible loss within frontend layout operations', '.governance-panel')
    page.field('规范依据与审阅理由', 'Human-confirmed synthetic normative policy, not a test result', '.governance-panel')
    page.click('确认存量分类与规范依据', '.governance-panel')
    wait(lambda: next(r for r in ledger()['rules'] if r['id'] == 'browser-legacy')['version'] == 2)
    page.until("document.querySelector('.detail-drawer').innerText.includes('无文件锚点')")
    page.js("document.querySelector('[aria-label=关闭抽屉]').click()")

    navigate('规则反馈与便签', '.feedback-view-root')
    page.click('重新分类 / 处理', '.feedback-view-root')
    page.field('已登记主题', 'frontend-layout', '.feedback-view-root')
    page.field('操作理由', 'Explicit finding reclassification', '.feedback-view-root')
    page.click('更新分类', '.feedback-view-root')
    wait(lambda: finding()['topics'] == ['frontend-layout'])
    navigate('项目设置与管理', panel)
    inspect('finding-only')
    page.field('操作理由', 'Its finding was explicitly reclassified', panel)
    page.click('删除无在用引用的主题', panel)
    wait(lambda: topic('finding-only')['status'] == 'deleted')

    navigate('规则反馈与便签', '.feedback-view-root')
    page.click('重新分类 / 处理', '.feedback-view-root')
    page.field('操作理由', 'Observation resolved explicitly', '.feedback-view-root')
    page.click('标记已处理', '.feedback-view-root')
    wait(lambda: finding()['status'] == 'resolved')
    page.until("document.querySelector('.findings-cards-flow').innerText.includes('已处理')")
    navigate('项目设置与管理', panel)
    assert page.js("[...document.querySelectorAll('.topics-panel button')].find(b=>b.textContent.includes('启用主题查询')).disabled")
    page.field('启用理由', 'Reviewed all active rules and pending observations', panel)
    assert not page.js("[...document.querySelectorAll('.topics-panel button')].find(b=>b.textContent.includes('启用主题查询')).disabled")
    page.click('确认分类完整，启用主题查询', panel)
    wait(lambda: ledger()['taxonomy']['topic_query_enabled'])
    page.until("document.querySelector('.topics-panel').innerText.includes('主题查询已启用')")

    navigate('规则作用域', '.inspect-panel')
    assert page.js("document.querySelectorAll('.inspect-panel input[type=checkbox]:checked').length") == 0
    page.fill('.inspect-inputs input', 'frontend/layout.vue')
    assert page.js("document.querySelector('.inspect-inputs button').disabled")
    page.js("document.querySelector('.inspect-panel input[value=P3]').click()")
    page.click('检查适用规则', '.inspect-panel')
    page.until("document.querySelector('.inspect-results')?.textContent.includes('Browser P3 guideline')")
    assert 'Browser legacy redline' not in page.js("document.querySelector('.inspect-results').textContent")
    assert page.js("document.body.innerText.includes('无文件锚点')")

    for width in (1024, 900, 768):
        page.cdp('Emulation.setDeviceMetricsOverride', {
            'width': width, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False})
        navigate('项目设置与管理', panel)
        page.until("getComputedStyle(document.querySelector('.nav-section-label')).display === 'none'")
        layout = page.js("""(() => {
          const sidebar = document.querySelector('.sidebar');
          const nav = document.querySelector('#navigation');
          const panel = document.querySelector('.topics-panel');
          return {
            headerHeight: sidebar.getBoundingClientRect().height,
            largestTab: Math.max(...[...nav.querySelectorAll('button')].map(b => b.getBoundingClientRect().width)),
            navigationWidth: nav.clientWidth,
            panelOverflow: panel.scrollWidth - panel.clientWidth,
            pageOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth
          };
        })()""")
        assert layout['headerHeight'] < 180, (width, layout)
        assert layout['largestTab'] < layout['navigationWidth'] / 2, (width, layout)
        assert layout['panelOverflow'] <= 1 and layout['pageOverflow'] <= 1, (width, layout)
        navigate('项目规则库', '.github-rules-table')
    page.cdp('Emulation.setDeviceMetricsOverride', {
        'width': 1280, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False})
    return ['topic_crud_and_tombstone', 'locked_boundary_and_delete_guard', 'legacy_rule_classification',
            'finding_reclassification_and_resolution', 'project_topic_cutover', 'explicit_p3_preview_and_pathless_rules',
            'responsive_navigation']

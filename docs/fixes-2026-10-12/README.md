# 2026-10-12 审查缺陷的修复验收证据

最终复核日期为 2026-10-13。原始审查证据仍保留在相邻的 `audit-2026-10-12/`，本目录只保存修复后的结果。

- `pytest-final.log`：完整后端测试结果。
- `build-final.log`：TypeScript 检查及静态前端构建结果。
- `browser-smoke.log`：独立新库“项目注册→需求提交→完成归档”冒烟结果。
- `browser-fix-results.json`：7 组产品验收，包含路径匹配、四种视口、错误注入、审阅差异、项目响应乱序、命令面板和规则抽屉。
- `browser-more-results.json`：补充的请求状态、内容宽度、统计口径、分页、工作区选择、路由、焦点和颜色检查。`pageErrors` 是浏览器 JavaScript 异常。
- `browser-visual-results.json`：七页在 390、768、1280、1440 四种宽度下的文案与排版检查，包含固定文案孤字、短控件换行、正文宽度、抽屉与关闭按钮。
- `browser-fix.log`、`browser-more.log`、`browser-visual.log`：对应脚本的最终运行输出；功能检查合计 20 组全部通过。
- `static-results.json`：当前源码未定义 CSS 变量、共享类及实际发布资源核查；对比度读取当前浏览器样式，见补充浏览器结果。
- `preservation-results.json`：原 58 项审查证据哈希与 270 个批次文件保留检查。
- `screenshots/`：60 张视觉检查截图及功能检查补充截图，包括全部七页、正文内容、任务/规则抽屉、状态流转与项目注册弹窗。`polished-{宽度}-{页面}.png` 是页面初始视图，`-content` 是重点阅读或操作区。留档时将 `browser-fix-results.json` 的截图路径改为本目录相对路径，检查结果保持不变。
- `visual-review.md`：人工查看截图后的结论和阅读宽度记录。
- `manifest.json`：本目录证据文件的 SHA-256，独立于原审查 manifest。

## 复现浏览器验收

`repro/seed.py` 只允许创建全新合成库；发现目标数据库已存在时会拒绝执行。浏览器脚本会创建、归档并发布合成任务，以及注入延迟/错误响应，只应连接该合成库服务。

在仓库根目录的 PowerShell 中，以新的临时目录准备数据：

```powershell
$sourceDir = (Get-Location).Path
$qaDir = Join-Path $env:TEMP ('codeneuro-fix-qa-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $qaDir | Out-Null
$env:PYTHONPATH = Join-Path $sourceDir 'src'
& '.venv/Scripts/python.exe' 'docs/fixes-2026-10-12/repro/seed.py' $sourceDir $qaDir
```

然后在单独终端启动临时服务，选择未被占用的本机端口：

```powershell
& '.venv/Scripts/python.exe' -B -m codeneuro serve --db "$qaDir/audit.db" --port 18974
```

等待 `/api/projects` 能访问后，运行脚本。环境变量可覆盖 Playwright 包和 Chrome 路径，不需要把依赖加进产品包：

```powershell
$env:CODENEURO_QA_DIR = $qaDir
$env:CODENEURO_QA_BASE = 'http://127.0.0.1:18974'
# $env:PLAYWRIGHT_MODULE = 'path/to/node_modules/playwright'
$env:CHROME_PATH = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
node docs/fixes-2026-10-12/repro/browser_fix_checks.cjs
node docs/fixes-2026-10-12/repro/browser_more_checks.cjs
node docs/fixes-2026-10-12/repro/browser_visual_checks.cjs
& '.venv/Scripts/python.exe' docs/fixes-2026-10-12/repro/static_quality.py $sourceDir $qaDir
& '.venv/Scripts/python.exe' docs/fixes-2026-10-12/repro/verify_preservation.py $sourceDir $qaDir
```

前两个浏览器脚本支持末尾追加单个检查名进行诊断；正式全量结果须不带该参数。结果写入新的 `$qaDir`，不会覆盖本目录的留档。用完后关闭自己启动的临时服务。截图检查等待抽屉动画完成后再测量，避免把过渡帧当作最终布局。

## 验收边界

这些结果覆盖原缺陷及其关键回归路径，不是对所有 256 项能力的重新打分。窄屏来自 Chromium 模拟视口；没有宣称经过实体手机、屏幕阅读器或生产数据迁移验收。原报告的 G01–G12 仍是后续能力建议。

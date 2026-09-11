import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(new URL('./start.bat', import.meta.url), 'utf8')

assert.doesNotMatch(source, /[^\x00-\x7F]/, '批处理文件必须保持 ASCII，避免 cmd.exe 解析中文乱码。')
assert.match(source, /start "" \/b "%PYTHON%" -m uvicorn/, '后端应在当前终端后台运行。')
assert.match(source, /call corepack pnpm exec vite --open --port 5173 --strictPort/, '前端应在当前终端运行并自动打开浏览器。')
assert.doesNotMatch(source, /for \/l %%i/, '脚本不应使用启动轮询。')
assert.match(source, /Invoke-RestMethod http:\/\/127\.0\.0\.1:8000\/health/, '脚本应复用已运行的后端。')
assert.match(source, /http:\/\/localhost:5173\/@vite\/client/, '脚本应复用已运行的前端。')
assert.match(source, /--port 5173 --strictPort/, '前端不应悄悄切换端口。')
assert.match(source, /node_modules\\@phosphor-icons\\react\\package\.json/, '脚本应校验图标依赖是否完整。')
assert.match(source, /call corepack pnpm install --force/, '缺失依赖时脚本应自动修复。')
assert.doesNotMatch(source, /Get-NetTCPConnection/, '修复不应依赖受限的网络连接查询。')
assert.match(source, /taskkill \/PID %%P \/T \/F/, '修复前仅应停止已确认的 Vite 进程。')
assert.ok((source.match(/@vite\/client/g) ?? []).length >= 2, '依赖修复后应重新识别前端服务。')

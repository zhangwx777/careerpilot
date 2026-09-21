import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const batchSource = readFileSync(new URL('./start.bat', import.meta.url), 'utf8')

assert.doesNotMatch(batchSource, /[^\x00-\x7F]/, '批处理必须保持 ASCII。')
assert.match(batchSource, /docker compose up --build/, '开发启动脚本应构建并启动 Compose 服务。')
assert.doesNotMatch(batchSource, /start\.ps1|powershell/i, '启动不应再经由 PowerShell 脚本。')
assert.doesNotMatch(batchSource, /uvicorn|celery|vite|pnpm/i, '开发启动脚本不应管理本机服务进程。')
assert.match(batchSource, /start "" http:\/\/127\.0\.0\.1:5173/, '就绪后应自动打开前端页面。')

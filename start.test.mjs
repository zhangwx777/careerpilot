import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const batchSource = readFileSync(new URL('./start.bat', import.meta.url), 'utf8')
const powershellSource = readFileSync(new URL('./start.ps1', import.meta.url), 'utf8')

assert.doesNotMatch(batchSource, /[^\x00-\x7F]/, '批处理包装器必须保持 ASCII。')
assert.match(
  batchSource,
  /powershell\.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0start\.ps1"/i,
  '批处理应调用独立的 PowerShell 脚本。',
)
assert.doesNotMatch(batchSource, /-Command/, '批处理不应内嵌多行 PowerShell 命令。')
assert.match(powershellSource, /\$PSScriptRoot/, 'PowerShell 脚本应从自身路径定位项目根目录。')
assert.match(powershellSource, /scripts\.init_db/, '启动时应初始化数据库。')
assert.match(powershellSource, /app\.main:app/, '启动脚本应启动 FastAPI 后端。')
assert.match(powershellSource, /openapi\.json/, '启动脚本应验证后端接口版本。')
assert.match(powershellSource, /llm\/providers/, '启动脚本应检查当前模型配置接口。')
assert.match(powershellSource, /corepack pnpm exec vite/, '启动脚本应启动 Vite 前端。')
assert.match(powershellSource, /Get-NetTCPConnection/, '启动脚本应检查端口占用。')
assert.match(powershellSource, /taskkill\.exe \/PID/, '启动脚本应只清理自己识别的项目进程。')
assert.match(powershellSource, /Stop-Process -Id \$processId -Force/, 'taskkill 被拒绝时应回退到 PowerShell 清理。')
assert.match(powershellSource, /Could not open the browser automatically/, '浏览器自动打开失败不应停止已启动的服务。')
assert.match(powershellSource, /\$backendPort = Find-Port 8000/, '每次启动都应为后端获取新鲜端口，避免复用旧进程。')
assert.match(powershellSource, /\$frontendPort = Find-Port 5173/, '每次启动都应为前端获取新鲜端口，避免复用旧进程。')

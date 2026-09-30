import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const compose = readFileSync(new URL('./docker-compose.yml', import.meta.url), 'utf8')
const backendDockerfile = readFileSync(new URL('./backend/Dockerfile', import.meta.url), 'utf8')
const frontendDockerfile = readFileSync(new URL('./frontend/Dockerfile', import.meta.url), 'utf8')
const dockerignore = readFileSync(new URL('./.dockerignore', import.meta.url), 'utf8')
const frontendDockerignore = readFileSync(new URL('./frontend/.dockerignore', import.meta.url), 'utf8')

for (const service of ['postgres:', 'redis:', 'backend:', 'worker:', 'frontend:']) {
  assert.match(compose, new RegExp(`^  ${service}`, 'm'), `Compose 必须声明 ${service}`)
}
assert.match(compose, /CELERY_BROKER_URL: redis:\/\/redis:6379\/0/)
assert.match(compose, /DATABASE_URL: postgresql\+psycopg:\/\/qiuzhao_app:qiuzhao_dev@postgres:5432\/qiuzhao/)
assert.match(compose, /VITE_API_TARGET: http:\/\/backend:8000/)
assert.match(compose, /condition: service_healthy/)
for (const port of [5432, 6379, 8000, 5173]) {
  assert.ok(compose.includes(`"127.0.0.1:${port}:${port}"`), `端口 ${port} 只能绑定到本机`)
}
assert.match(backendDockerfile, /python:3\.12-slim/)
assert.match(backendDockerfile, /pip install --no-cache-dir "\/workspace\/backend\[test\]"/)
assert.match(compose, /context: \.\/backend/)
assert.match(compose, /\/docker-entrypoint-initdb\.d/)
const testDbInit = readFileSync(new URL('./docker/postgres-init/01-create-test-db.sql', import.meta.url), 'utf8')
assert.match(testDbInit, /CREATE DATABASE qiuzhao_test/)
const backendDockerignore = readFileSync(new URL('./backend/.dockerignore', import.meta.url), 'utf8')
assert.match(backendDockerignore, /\.venv/)
assert.match(backendDockerignore, /\.pytest_cache/)
assert.match(frontendDockerfile, /node:22-bookworm-slim/)
assert.match(frontendDockerfile, /pnpm install --frozen-lockfile/)
assert.match(dockerignore, /\.pytest_cache/)
assert.match(frontendDockerignore, /node_modules/)
assert.match(frontendDockerignore, /dist/)

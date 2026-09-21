# 当前进度记忆

更新时间：2026-09-21

## 当前基线

- 以当前工作树为准；仓库存在 Claude/本地未提交改动，不以 `v0.1.0` 提交作为最新实现。
- 开发环境已统一为 Docker Compose：`start.bat` 负责启动 frontend、backend、worker、PostgreSQL 和 Redis。
- 桌面包代码已采用分层结构：`packaging/build.ps1` 复制前端构建和后端明文源码到 `app`，把 PyInstaller 启动器、PostgreSQL、Garnet/.NET 和 Electron 壳放到 `runtime`/包根目录。
- 桌面启动器 `desktop/main.cjs` 自己管理 PostgreSQL、Garnet、backend 和 worker，并通过动态本地端口启动，不依赖开发机服务。
- 前端近期 UI 改动位于 `frontend/src/styles.css`、`frontend/index.html`、`frontend/public/brand-mark.png`，当前开发构建已重新生成。

## 已验证

- 前端单元测试：9/9 通过。
- 前端生产构建：通过；当前 `frontend/dist` 生成于 2026-09-21 17:06。
- 桌面端口选择与开发启动脚本测试：2/2 通过。
- 安装器契约测试：10/10 通过。
- `backend/app` 与 `packaged_server.py` 当前源码和 staging payload 内容一致。

## 未同步项

- `dist/CareerPilot-portable.zip` 生成于 13:25，包内前端资源生成于 13:05；`dist/CareerPilotSetup.exe` 生成于 13:38。
- 当前安装包仍包含旧 UI 构建：包内 `brand-mark.png` 为 706,274 字节，当前源码图为 40,807 字节；包内 CSS/JS 文件名也不同于当前 `frontend/dist`。
- 因此当前安装包尚未同步最新前端 UI。后端应用层和桌面壳没有发现源码漂移。
- `packaging/build.ps1 -AppOnly` 只刷新 staging 的 `build/installer/payload/app` 后直接返回，不会重新生成 `dist` 下的 zip 或 Setup.exe；要交付同步安装包，必须运行完整 `packaging/build.ps1`。

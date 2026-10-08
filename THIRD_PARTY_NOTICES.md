# 第三方组件许可说明

CareerPilot 桌面发行包包含或分发下列第三方组件。各组件仍按其自身许可发布；对应许可正文随安装包或便携包一同提供。

| 组件 | 许可/声明文件位置 |
| --- | --- |
| Electron 与 Chromium | 安装包根目录的 `LICENSE`、`LICENSES.chromium.html` |
| .NET Runtime | `runtime/dotnet/LICENSE.txt`、`runtime/dotnet/ThirdPartyNotices.txt` |
| Python 运行时依赖 | `runtime/backend/_internal/*dist-info/licenses/` |
| 前端 JavaScript 依赖 | `licenses/frontend/` |
| Microsoft Garnet | `licenses/garnet/Garnet-LICENSE.txt` |
| PostgreSQL 及命令行工具 | `licenses/postgresql/` |

版本和来源：

- Electron 版本由 `packaging/build.ps1` 中的 `electron-version` 参数固定。
- Garnet 版本由同一脚本中的 `garnetVersion` 固定，许可正文来自对应上游版本。
- PostgreSQL 主版本由构建脚本和开发文档指定，发行包保留该安装目录提供的服务器许可及命令行工具第三方声明。
- Python 和前端依赖版本由 `backend/requirements.lock`、`frontend/pnpm-lock.yaml` 锁定；包内许可文件随锁定依赖收集。

如第三方许可与本项目 MIT 许可存在差异，以对应组件随附的许可文本为准。

# 职航 CareerPilot

[![Verify](https://github.com/zhangwx777/careerpilot/actions/workflows/verify.yml/badge.svg?branch=main)](https://github.com/zhangwx777/careerpilot/actions/workflows/verify.yml)

职航 CareerPilot 是一款面向校园招聘的 Windows 桌面求职工作台。它帮助你集中管理投递、招聘日程、面经和面试准备，并根据当前资料安排接下来的求职行动。

CareerPilot 不会自动投递或替你做决定。AI 提供的解析和建议都由你确认后再使用。

## 主要功能

- 管理公司、岗位、投递阶段及笔试、面试和截止日期。
- 粘贴招聘通知，提取岗位和日程信息，核对后再保存。
- 按公司和岗位整理面经文字与截图，并查看带资料来源的岗位问答。
- 结合岗位信息、面经和简历生成准备行动，支持练习和自我评估。
- 汇总待办求职节点，帮助安排接下来的工作。

## 安装

从 [最新 Release](https://github.com/zhangwx777/careerpilot/releases/latest) 下载适合你的 Windows x64 版本：

- **CareerPilotSetup.exe**：标准安装版，可创建桌面和开始菜单快捷方式。
- **CareerPilot-portable.zip**：便携版，解压后运行 CareerPilot.exe。

首次启动后，在“模型设置”中配置你选择的模型服务和 API Key。模型调用及可选的公开资料检索需要网络连接。安装包未进行代码签名，Windows 可能显示发布者提示。

应用数据保存在当前 Windows 用户的 %LOCALAPPDATA%\CareerPilot 目录中。安装或更新不会要求你另行安装 Python、Node.js、PostgreSQL 或 Redis。

## 数据与帮助

投递记录、简历和面经保存在本机。使用模型或联网检索时，相关内容会发送到你配置的服务提供方；请按需查阅该服务提供方的数据政策。

遇到可复现的问题，可在 [GitHub Issues](https://github.com/zhangwx777/careerpilot/issues) 提交反馈。提交前请删除日志、截图和描述中的 API Key、密码、简历及个人求职信息。安全漏洞请通过 [私密漏洞报告](https://github.com/zhangwx777/careerpilot/security/advisories/new) 提交，不要在公开 Issue 中披露细节。

## 许可证

CareerPilot 使用 MIT 许可证，详见 [LICENSE](LICENSE)。桌面发行包中的第三方组件遵循各自许可，见[第三方组件许可说明](THIRD_PARTY_NOTICES.md)。

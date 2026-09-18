# 本地安装与维护

普通用户请按 [README.md](README.md) 操作：安装 Python 3.12，运行 `install.bat`，填写 `models.json`，运行 `start.bat`。

安装脚本将虚拟环境建立在项目自己的 `.venv` 内。启动脚本优先使用它；为兼容原开发目录，找不到时才检查上一级 `.venv`。新用户无需手动建立上级目录。

PowerShell 等价命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\start.ps1
```

源代码开发目录如果包含完整 `tests` 和测试样例，可运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
```

为排除原卷内容，当前面向用户的发布副本未包含历史 `tests` 目录，不应把未运行测试当作测试通过。

## 上传与备份

Git 提交前检查 `git status` 和 `git diff --cached`。不上传 `.env`、`models.json`、`mcp.json`、`data/`、`outputs/`、个人笔记、试卷和媒体。

GitHub 网页拖拽上传不会根据 `.gitignore` 筛选文件。安装、使用后的项目目录会产生个人配置和数据，不能直接全选再次上传。上传新版本时只选择代码、说明、脚本和示例配置。

数据备份与升级步骤见 README。`update_and_restart.bat` 只安装依赖并重启，不拉取远程代码。

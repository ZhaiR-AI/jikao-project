# 成考英语学习与试卷生成系统

在自己的 Windows 电脑上运行：导入 PDF 试卷、生成可作答的试题、判卷并管理错题和学习记录。

本仓库只提供程序，不附带作者的卷子、学习资料、API Key 或个人记录。首次启动时试卷列表为空，需要导入自己的 PDF。

## 普通用户：下载 Windows 便携版

**不懂编程、没有安装 Python？请使用便携版。**

1. 打开 [软件下载页（Releases）](https://github.com/ZhaiR-AI/jikao-project/releases)，选择 Windows 便携试用版。
2. 下载 Assets 中的 **Chengkao-Windows-x64-….zip**，不要下载名为 Source code 的源码包。
3. 右键“全部解压”，直接解压到桌面等较短路径，避免套多层文件夹，再双击 **启动成考助手.exe**。若提示路径过长，请换短目录重新完整解压，不要跳过错误。
4. 在中文窗口填写自己的接口地址、模型名称和 API Key，点击“保存配置并启动”。浏览器会自动打开。
5. 以后再次双击 EXE，软件会读取已保存的配置并启动。关闭启动窗口时停止服务。

适用于 Windows 10/11 x64，自带运行环境，不需要安装 Python、Codex，也不需要输入命令或手动编辑配置文件。模型服务仍需用户自行开通，费用由所选平台收取。

不会填写三项信息时，查看 [新手模型配置教程](docs/MODEL_SETUP.md)。包内也有可直接打开的“使用说明.html”。首次建议用一页完整小卷子验证生成和判卷。

便携版数据在 `程序文件/app/data`，配置在 `程序文件/app/models.json`。更新前停止程序并备份，然后把自己的数据和配置复制到新版本的相同位置。试用包尚未进行商业代码签名，Windows 可能提示未知发布者，请核对下载来源。

**以下是源码版安装方法，便携版用户可以跳过。**

## 使用前准备

- Windows 10 / 11；本教程和批处理脚本面向 Windows。
- Python **3.12（64 位）**。从 https://www.python.org/downloads/windows/ 下载 3.12 的 Windows installer (64-bit)，安装时勾选 **Add python.exe to PATH**，保留 Python Launcher。
- 安装依赖需要联网。模型生成、识别和 AI 判卷需要你自己的模型服务账号与 API Key，费用由你的服务商收取。
- 用于 PDF 识别的模型必须支持图片输入，接口应兼容 OpenAI API。本项目不会提供免费的模型额度。

## 1. 下载并解压

在 GitHub 仓库首页点击绿色 **Code → Download ZIP**，下载后右键“全部解压”。进入包含 `start.bat` 和 `requirements.txt` 的目录。

不要直接在压缩包中运行。建议解压到自己的固定目录，例如 `D:\chengkao-project`。

## 2. 首次安装

双击 **install.bat**，等待出现 `Installation complete`。

安装程序会在项目文件夹内创建 `.venv`，安装依赖，并从模板创建 `models.json` 和 `.env`。重复运行不会覆盖已有配置和学习数据。首次安装可能需要几分钟；失败时窗口会保留错误信息，可以修复网络或 Python 安装后重试。

## 3. 填写自己的模型配置

**新手建议直接按 [模型配置教程](docs/MODEL_SETUP.md) 操作**：获取接口地址、模型名称、API Key，然后在安装生成的文件中只修改这三项。下面的完整 JSON 供需要重新建立配置时参考。

用记事本打开 **models.json**。只使用试卷功能时，可以把内容替换成下面这个最小配置，再填写服务商提供的实际值：

```json
{
  "default": "my-vision-model",
  "fallback": "my-vision-model",
  "fast": "my-vision-model",
  "vision": "my-vision-model",
  "models": [
    {
      "id": "my-vision-model",
      "channel": "openai",
      "type": "chat",
      "supports_vision": true,
      "model": "填写服务商的真实模型名称",
      "base_url": "https://你的服务商接口地址/v1",
      "api_key": "填写你自己的API密钥"
    }
  ]
}
```

- `id` 是本地别名；上面的 `default`、`fallback`、`fast`、`vision` 都引用它，可以保持示例中的名称。
- **model** 必须填写服务商实际支持的模型标识，并确认该模型支持图片。设置 `supports_vision: true` 本身不会让纯文本模型获得识图能力。
- **base_url** 使用服务商文档中的 API 基础地址，通常以 `/v1` 结尾，不要填聊天网页地址或完整的 `/chat/completions` 地址。
- **api_key** 填你自己的密钥。不要把配置文件或带密钥的截图发到 GitHub、群聊或问题反馈里。
- 保存为 UTF-8 的 `models.json`，注意不要变成 `models.json.txt`。保留 JSON 的英文双引号和逗号。

普通本地试卷功能不需要填写 `.env` 中的数据库配置，也不需要运行 Docker 或另外安装 Node.js。改动模型配置后重启程序生效。

## 4. 启动和使用

双击 **start.bat**，保留打开的命令窗口，然后在浏览器访问：

- 试卷页面：http://127.0.0.1:8020/exam
- 学习页面：http://127.0.0.1:8020/study
- 错题本：http://127.0.0.1:8020/wrong-book

在试卷页面选择 **上传 PDF 生成试卷**，选择自己的 PDF 后点击 **生成试卷**。第一次建议使用一份页数较少、文字清楚的 PDF，确认 API 配置和生成结果正常后再处理长卷。AI 识别、答案和判卷结果可能有误，请结合原卷核对。

命令窗口中按 **Ctrl+C** 停止服务。下次使用只需双击 `start.bat`，不用重复安装。这个本地地址只能访问自己电脑上的程序。

## 数据保存、备份和更新

试卷、上传文件、作答和学习记录保存在项目的 `data` 文件夹内。它会在运行后自动创建。请定期在停止程序后备份 `data`，并另外妥善保存自己的 `models.json` 和 `.env`。

更新时先停止程序并备份上述文件，再下载新版本，把新版本的程序文件复制到原目录覆盖。保留原来的 `data`、`models.json` 和 `.env`。然后运行 `install.bat` 更新依赖，再运行 `start.bat`。

`update_and_restart.bat` 是已经替换代码后的快捷入口：安装依赖并重启本地服务，**不会自动从 GitHub 下载代码**。

不要删除整个旧目录后直接使用新目录，否则旧目录中的个人数据不会自动迁移。

## 常见问题

| 情况 | 处理方式 |
| --- | --- |
| 找不到 Python、`No suitable Python runtime found` | 安装 Python 3.12（64 位），保留 Launcher 并勾选 PATH，再运行 `install.bat`。 |
| `Dependency installation failed` | 查看窗口中 pip 的错误信息，确认能联网后重新运行 `install.bat`。 |
| `Python environment not found` | 先运行 `install.bat`，不要只复制启动脚本。 |
| 端口 8020 被占用 | 检查是否已启动过一次；也可在项目目录的 PowerShell 中运行 `powershell -ExecutionPolicy Bypass -File .\start.ps1 -Port 8021`，然后访问 `http://127.0.0.1:8021/exam`。 |
| 网页打不开 | 确认启动窗口还开着且没有报错，核对终端显示的网址和端口。 |
| 模型返回 401 / 403 | 核对自己的 API Key、服务商地址和账号权限。 |
| 模型不存在或不支持图片 | 核对 `model` 的实际名称和服务商的图片输入支持。 |
| 模型返回 429 | 查看服务商余额、配额和并发限制，降低 OCR 并发或稍后重试。 |
| 页面能打开，但生成失败 | 页面打开只代表本地服务正常；还需要有效的模型配置、可用的网络和模型额度。 |
| 试卷列表为空 | 新安装本来没有个人卷子，请自行导入 PDF。 |

## 反馈问题

请在 GitHub Issues 中说明 Windows 版本、操作步骤、错误提示和 Python 版本（运行 `py -3.12 --version`）。截图前遮住密钥和个人信息。不要提交自己的 `data` 或真实配置文件。

当前发布副本没有附带包含原卷内容的历史测试数据，因此不包含完整的自动化测试集。支持范围和实际验证结果以发布说明为准。

## 项目设计

原有功能规划和设计说明保存在 [项目设计文档](docs/PROJECT_DESIGN.md)。其中的规划不等于已验证的发布功能。

## 发布验证

当前依赖版本记录在 constraints.txt，安装时会自动使用。已完成的检查和未验证范围见 [发布检查记录](docs/RELEASE_CHECKS.md)。

## 许可证

本项目采用 [Apache License 2.0](LICENSE)。使用、修改和分发本项目时，请遵守许可证中的声明保留等要求。第三方依赖仍遵循各自的许可证。

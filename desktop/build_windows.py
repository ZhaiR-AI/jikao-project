"""Build the portable Windows ZIP using an isolated, installed Python 3.12 env."""
from __future__ import annotations

import argparse
import html
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MODULES = [
    "cet4_parser.py", "collection_categories.py", "generation_jobs.py", "document_reader.py",
    "paper_generator.py", "paper_quality.py", "paper_routes.py", "paper_server.py",
    "paper_trash.py", "pdf_reader.py", "phrase_coverage.py", "study_routes.py",
    "study_store.py", "wrong_book_records.py", "wrong_book_review.py",
]
PYTHON_VERSION = "3.12.10"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="0.1.0")
    parser.add_argument("--site-packages", type=Path, default=Path(sysconfig.get_path("purelib")))
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    if os.name != "nt" or sys.version_info[:2] != (3, 12):
        raise SystemExit("Build on 64-bit Windows with Python 3.12.")
    # A fresh output directory prevents accidentally packaging previous users' data.
    package = args.output.resolve() / ("Chengkao-Windows-x64-v" + args.version)
    package.mkdir(parents=True, exist_ok=False)
    app = package / "程序文件" / "app"
    runtime = package / "程序文件" / "python"
    app.mkdir(parents=True)
    runtime.mkdir()
    for name in MODULES:
        shutil.copy2(ROOT / name, app / name)
    for name in ("agents", "static"):
        shutil.copytree(ROOT / name, app / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(ROOT / "desktop" / "desktop_server.py", app / "desktop_server.py")
    shutil.copy2(ROOT / "models.example.json", app / "models.example.json")
    shutil.copy2(ROOT / "LICENSE", package / "LICENSE")
    shutil.copy2(ROOT / "constraints.txt", package / "依赖版本.txt")
    shutil.copytree(ROOT / "docs", package / "docs")
    (package / "使用说明.html").write_text(HELP, encoding="utf-8")
    (package / "第三方软件说明.txt").write_text(
        "项目代码采用 Apache-2.0。Python 及依赖各自遵循其许可证。\n"
        "Python 许可见 程序文件/python/LICENSE.txt；依赖许可和作者信息保留在\n"
        "程序文件/python/Lib/site-packages 下各包的 dist-info、licenses 等目录中。\n"
        "本发行包并未把第三方软件的许可证改为 Apache-2.0。\n", encoding="utf-8")
    print("Downloading official embedded Python ...", flush=True)
    cache = args.output.resolve() / ("python-" + PYTHON_VERSION + "-embed-amd64.zip")
    if not cache.exists():
        urllib.request.urlretrieve("https://www.python.org/ftp/python/" + PYTHON_VERSION + "/" + cache.name, cache)
    with zipfile.ZipFile(cache) as archive:
        archive.extractall(runtime)
    (runtime / "python312._pth").write_text("python312.zip\n.\nLib/site-packages\n../app\nimport site\n", encoding="ascii")
    print("Bundling dependencies and their license metadata ...", flush=True)
    shutil.copytree(args.site_packages, runtime / "Lib" / "site-packages",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
    compiler = Path(os.environ["WINDIR"]) / "Microsoft.NET" / "Framework64" / "v4.0.30319" / "csc.exe"
    print("Compiling the native launcher ...", flush=True)
    subprocess.run([str(compiler), "/nologo", "/target:winexe", "/platform:x64", "/utf8output",
                    "/r:System.Windows.Forms.dll", "/r:System.Drawing.dll", "/r:System.Web.Extensions.dll",
                    "/out:" + str(package / "启动成考助手.exe"), str(ROOT / "desktop" / "Launcher.cs")], check=True)
    # Test the distributed runtime itself without system Python or Python environment vars.
    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env["PATH"] = os.path.join(os.environ["WINDIR"], "System32")
    env["PYTHONIOENCODING"] = "utf-8"
    print("Checking embedded runtime imports ...", flush=True)
    subprocess.run([str(runtime / "python.exe"), "-B", "-c",
                    "import sys, ssl, fitz, fastapi, agentclaw; assert sys.flags.isolated; print(sys.executable)"],
                   cwd=app, env=env, check=True)
    if any((app / name).exists() for name in ("data", "models.json", ".env")):
        raise RuntimeError("Private or test data found in distribution")
    print("Compressing portable package ...", flush=True)
    archive = shutil.make_archive(str(package), "zip", root_dir=package.parent, base_dir=package.name)
    import hashlib
    digest = hashlib.file_digest(open(archive, "rb"), "sha256").hexdigest()
    Path(archive + ".sha256").write_text(digest + "  " + Path(archive).name + "\n", encoding="ascii")
    print(json.dumps({"package": str(package), "archive": archive, "sha256": digest}, ensure_ascii=False), flush=True)


HELP = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>成考助手 · 使用说明</title><style>body{font:17px/1.85 system-ui,sans-serif;max-width:850px;margin:40px auto;padding:0 24px;color:#17263d;background:#f7f9fc}section{background:white;border:1px solid #dbe3ed;border-radius:16px;padding:24px;margin:20px 0}h1,h2{line-height:1.4}code{background:#eef2f7;padding:2px 6px}a{color:#185abd}li{margin:8px 0}</style>
<h1>成考助手 · Windows 便携版</h1><p>适用于 Windows 10/11 的 64 位电脑。无需安装 Python，无需输入命令。</p>
<section><h2>选模型前必看</h2><p><strong>导入 PDF 必须使用支持图片输入和文字识别的多模态大模型（视觉模型）。</strong> PDF 一律逐页转成图片识别，不直接使用内嵌文字层。请确认模型和平台 API 都支持图片输入；纯文字聊天或只能生成图片的模型不适用于 PDF。</p><p>DOCX、TXT、Markdown 先读取文字，再交给大模型整理。含图片、公式对象或复杂自动编号的 Word 请先导出为 PDF；旧版 .doc 请另存为 .docx 或 PDF。听力原卷若只有选项，需自行播放配套音频。</p></section>
<section><h2>第一次使用</h2><ol><li>右键 ZIP，选择“全部解压”，直接解压到桌面等较短路径。不要放进多层文件夹，否则 Windows 可能提示路径过长、无法解压。不要在压缩包内运行，不要只复制 EXE。</li>
<li>双击“启动成考助手.exe”。</li><li>填写模型平台提供的<b>接口地址、模型名称和 API Key</b>，点击“保存配置并启动”。</li>
<li>浏览器会自动打开试卷页面。第一次选一份只有一页、题目完整的 PDF，验证生成和判卷。</li></ol>
<p>以后双击 EXE 即可，已保存配置会自动载入。暂时没有模型配置，也可以点“打开页面”浏览界面。</p></section>
<section><h2>三项信息去哪里找？</h2><p>注册你选择的模型平台，进入开发者控制台：在“API 密钥”中创建密钥，在接口文档中找到 Base URL 和模型 ID。</p>
<p>处理 PDF 时模型必须支持图片输入；平台必须提供兼容 OpenAI Chat Completions 的接口。聊天会员不等于 API 额度。</p>
<ul><li><b>接口地址：</b>平台的 API 基础地址，不是聊天网页地址，不要加末尾的 /chat/completions。</li><li><b>模型名称：</b>复制平台文档中的模型 ID，注意版本后缀。</li><li><b>API Key：</b>你自己的调用密钥。默认隐藏，勿向他人发送。</li></ul>
<p><a href="https://github.com/ZhaiR-AI/jikao-project/blob/main/docs/MODEL_SETUP.md">查看详细教程及常见报错说明</a>（便携版在启动窗口填写，不需要手改 JSON）。</p>
<p>识别、生成和 AI 判卷会把相关内容发给你选择的模型平台，使用你的额度，可能产生费用。能打开网页不代表模型已连接成功。</p></section>
<section><h2>数据和更新</h2><p>点击启动窗口的“数据目录”可找到自己的卷子和学习记录。实际位置是 <code>程序文件/app/data</code>；模型配置在同一层的 <code>models.json</code>。</p>
<p>更新前停止程序，备份 data、models.json（如有 .env 也一并备份）。解压新版本后，把这些文件复制到新版本的同一位置。不要直接删除旧文件夹。</p>
<p>关闭启动窗口会停止服务。关闭前保存作答，等待生成或判卷完成；只关浏览器不会停止服务。</p></section>
<section><h2>打不开怎么办？</h2><ul><li>确认已经完整解压，并把整个软件文件夹放在桌面等可写的短目录。若解压报“路径太长”或“找不到文件”，请换一个更短的位置重新完整解压，例如有 D 盘时使用 D:\\Chengkao。不要跳过报错后继续运行不完整的文件。</li><li>使用 Windows 10/11 64 位系统。首次启动可能需要稍等。</li><li>查看同目录的“启动日志.txt”。反馈前遮住密钥和个人内容。</li><li>此试用包尚未进行商业代码签名，Windows 可能显示未知发布者。请核对下载来自项目官方 Releases，不要关闭系统防护。</li></ul>
<p><a href="https://github.com/ZhaiR-AI/jikao-project/issues">反馈问题</a> · <a href="https://github.com/ZhaiR-AI/jikao-project">项目主页</a></p></section></html>'''


if __name__ == "__main__":
    main()

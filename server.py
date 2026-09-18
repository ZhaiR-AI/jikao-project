"""
AgentClaw 服务入口

启动方式：
  agentclaw serve
  # 或
  python server.py
"""

# 导入 agents 模块，自动注册所有工作流
import agents  # noqa: F401
from paper_routes import mount_paper_app

import os

from agentclaw import AgentClawServer


class PaperGenerationServer(AgentClawServer):
    def __init__(self, *args, **kwargs):
        os.environ.setdefault("AGENTCLAW_MAX_REQUEST_BODY_BYTES", str(256 * 1024 * 1024))
        os.environ.setdefault("MAX_UPLOAD_SIZE_MB", "256")
        super().__init__(*args, **kwargs)

    def _create_app(self):
        app = super()._create_app()
        mount_paper_app(app)
        return app

# 如果直接运行此文件，启动服务器
if __name__ == "__main__":
    server = PaperGenerationServer()
    server.run()

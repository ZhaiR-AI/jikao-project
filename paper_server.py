from __future__ import annotations

import os

import uvicorn
from fastapi import FastAPI

# Import workflows so AgentClaw registers and initializes the graph definitions.
import agents  # noqa: F401
from paper_routes import mount_paper_app


def create_app() -> FastAPI:
    os.environ.setdefault("AGENTCLAW_MAX_REQUEST_BODY_BYTES", str(256 * 1024 * 1024))
    os.environ.setdefault("MAX_UPLOAD_SIZE_MB", "256")
    app = FastAPI(title="Paper Exam Server")
    mount_paper_app(app)
    return app


app = create_app()


if __name__ == "__main__":
    host = os.getenv("PAPER_HOST", "127.0.0.1")
    port = int(os.getenv("PAPER_PORT", "8020"))
    uvicorn.run("paper_server:app", host=host, port=port, reload=False)

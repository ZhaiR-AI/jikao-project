"""Portable desktop entry point; lifecycle is owned by the Windows launcher."""
from __future__ import annotations

import asyncio
import ctypes
import os

import uvicorn
from fastapi import Header, HTTPException
from paper_server import create_app


app = create_app()
token = os.environ["PAPER_DESKTOP_TOKEN"]
server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=int(os.environ["PAPER_PORT"])))


def authorize(value):
    import secrets
    if not value or not secrets.compare_digest(value, token):
        raise HTTPException(403, "仅供本地启动器使用")


@app.get("/_desktop/status", include_in_schema=False)
async def status(x_desktop_token: str | None = Header(default=None)):
    authorize(x_desktop_token)
    return {"ready": True}


@app.post("/_desktop/stop", include_in_schema=False)
async def stop(x_desktop_token: str | None = Header(default=None)):
    authorize(x_desktop_token)
    server.should_exit = True
    return {"stopping": True}


async def watch_parent():
    """Stop even if the launcher is closed by Task Manager."""
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    handle = kernel.OpenProcess(0x00100000, False, int(os.environ["PAPER_DESKTOP_PARENT"]))
    if not handle:
        server.should_exit = True
        return
    try:
        while not server.should_exit:
            if kernel.WaitForSingleObject(handle, 0) == 0:
                server.should_exit = True
                return
            await asyncio.sleep(1)
    finally:
        kernel.CloseHandle(handle)


async def main():
    watcher = asyncio.create_task(watch_parent())
    try:
        await server.serve()
    finally:
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())

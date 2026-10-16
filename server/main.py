from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

server_dir = str(Path(__file__).resolve().parent)
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from models import CrawlResponse
from weibo import CrawlError as WeiboCrawlError, crawl_weibo

app = FastAPI(title='政审分析爬虫接口')
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.get('/api/crawl', response_model=CrawlResponse)
async def crawl(
    platform: str = Query(..., description='平台：微博'),
    account: str = Query(..., min_length=1, description='账号昵称或 ID'),
    limit: int = Query(20, ge=1, le=100, description='抓取条数限制，默认20条'),
    cookie: str | None = Query(None, description='微博 Cookie'),
) -> CrawlResponse:
    if platform == '微博':
        try:
            return await crawl_weibo(account, limit=limit, cookie=cookie)
        except WeiboCrawlError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    if platform == '小红书':
        raise HTTPException(status_code=400, detail='小红书抓取已改为在桌面客户端内完成，请使用桌面客户端')
    raise HTTPException(status_code=400, detail=f'不支持的平台：{platform}')


def _exit_when_parent_exits() -> None:
    """作为桌面端 sidecar 运行时，stdin 是连接到主程序的管道；主程序退出（包括被强制结束）时管道关闭，
    这里读到 EOF 后立即退出，避免后端成为孤儿进程长期占用 8000 端口。"""
    stdin = sys.stdin
    if stdin is None or stdin.isatty():
        return

    def watch() -> None:
        try:
            while stdin.buffer.read(1024):
                pass
        except Exception:
            pass
        os._exit(0)

    threading.Thread(target=watch, daemon=True).start()


if __name__ == '__main__':
    _exit_when_parent_exits()
    uvicorn.run(app, host='127.0.0.1', port=8000)

from __future__ import annotations

import sys
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


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8000)

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
from xiaohongshu import CrawlError as XhsCrawlError, crawl_xiaohongshu

app = FastAPI(title='政审分析爬虫接口')
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['GET'],
)


@app.get('/api/crawl', response_model=CrawlResponse)
async def crawl(
    platform: str = Query(..., description='平台：微博 / 小红书'),
    account: str = Query(..., min_length=1, description='账号昵称或 ID'),
    limit: int = Query(20, ge=1, le=100, description='抓取条数限制，默认20条'),
) -> CrawlResponse:
    if platform == '微博':
        try:
            return await crawl_weibo(account, limit=limit)
        except WeiboCrawlError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
    if platform == '小红书':
        try:
            return await crawl_xiaohongshu(account, limit=limit)
        except XhsCrawlError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"小红书抓取异常: {e}") from e
    raise HTTPException(status_code=400, detail=f'不支持的平台：{platform}')


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8000)

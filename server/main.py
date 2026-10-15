import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from models import CrawlResponse
from weibo import CrawlError, crawl_weibo

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
        except CrawlError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
    if platform == '小红书':
        raise HTTPException(
            status_code=400,
            detail='小红书需要登录 Cookie 与请求签名，暂未接入，请先用微博演示',
        )
    raise HTTPException(status_code=400, detail=f'不支持的平台：{platform}')


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8000)

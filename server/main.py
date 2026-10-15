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
from xiaohongshu import CrawlError as XhsCrawlError, crawl_xiaohongshu, interactive_login

app = FastAPI(title='政审分析爬虫接口')
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_methods=['*'],
    allow_headers=['*'],
)


@app.get('/api/crawl', response_model=CrawlResponse)
async def crawl(
    platform: str = Query(..., description='平台：微博 / 小红书'),
    account: str = Query(..., min_length=1, description='账号昵称或 ID'),
    limit: int = Query(20, ge=1, le=100, description='抓取条数限制，默认20条'),
    cookie: str | None = Query(None, description='自定义Cookie（例如微博）'),
) -> CrawlResponse:
    if platform == '微博':
        try:
            return await crawl_weibo(account, limit=limit, cookie=cookie)
        except WeiboCrawlError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    if platform == '小红书':
        try:
            return await crawl_xiaohongshu(account, limit=limit)
        except XhsCrawlError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"小红书抓取异常: {e}") from e
    raise HTTPException(status_code=400, detail=f'不支持的平台：{platform}')


@app.post('/api/xhs/login')
async def xhs_login():
    """打开浏览器供用户扫码登录小红书，自动保存登录态到本地 profile"""
    try:
        ok = await interactive_login()
        if ok:
            return {'ok': True, 'message': '小红书登录成功，登录态已持久化保存'}
        return {'ok': False, 'message': '未检测到登录成功或登录已超时'}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'启动扫码窗口失败: {e}') from e


if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8000)

from __future__ import annotations

from pydantic import BaseModel


class Post(BaseModel):
    time: str
    likes: int
    content: str


class CrawlResponse(BaseModel):
    platform: str
    account: str
    posts: list[Post]

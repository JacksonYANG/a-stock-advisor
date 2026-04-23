#!/usr/bin/env python3
"""
舆情分析模块
基于东方财富接口获取个股新闻/公告，进行简单情感分析
"""

import requests
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime


@dataclass
class NewsItem:
    """新闻条目"""
    title: str = ""
    url: str = ""
    publish_time: str = ""
    source: str = ""
    sentiment: str = ""   # positive / negative / neutral
    sentiment_score: float = 0.0  # -1 to 1


class NewsFetcher:
    """新闻获取器"""

    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.eastmoney.com",
        }

    def get_stock_news(self, code: str, limit: int = 10) -> List[NewsItem]:
        """
        获取个股新闻
        使用东方财富个股资讯接口
        code: 东方财富格式，如 sh.600519 或 sz.000001
        """
        results = []
        url = f"https://np-anotice-stock.eastmoney.com/api/security/ann?sr=-1&page_size={limit}&page_index=1&ann_type=SHA%2CSZA&client_source=web&stock_list={code}"

        try:
            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                items = data.get("data", {}).get("list", [])
                for item in items:
                    news = NewsItem(
                        title=item.get("title", ""),
                        url=item.get("art_url", ""),
                        publish_time=item.get("notice_date", ""),
                        source="东方财富",
                    )
                    news.sentiment, news.sentiment_score = self._analyze_sentiment(news.title)
                    results.append(news)
        except Exception:
            pass

        return results

    def _analyze_sentiment(self, text: str) -> tuple:
        """
        简单情感分析 - 基于关键词打分
        Returns: (sentiment: str, score: float)
        """
        if not text:
            return "neutral", 0.0

        positive_words = ["增长", "盈利", "突破", "创新高", "扩张", "合作", "中标", "业绩", "提升", "超额", "增持", "推荐", "买入", "评级上调", "大幅增长", "扭亏为盈", "超预期"]
        negative_words = ["下降", "亏损", "风险", "减持", "卖出", "预警", "下调", "违规", "处罚", "诉讼", "暴跌", "破发", "ST", "带帽", "退市", "业绩下滑", "首亏", "大幅下降"]

        score = 0.0
        for w in positive_words:
            if w in text:
                score += 0.2
        for w in negative_words:
            if w in text:
                score -= 0.2

        score = max(-1.0, min(1.0, score))

        if score > 0.1:
            sentiment = "positive"
        elif score < -0.1:
            sentiment = "negative"
        else:
            sentiment = "neutral"

        return sentiment, score


_news_fetcher = None


def get_news_fetcher() -> NewsFetcher:
    global _news_fetcher
    if _news_fetcher is None:
        _news_fetcher = NewsFetcher()
    return _news_fetcher
# -*- coding: utf-8 -*-
"""
大盘复盘市场区域配置

定义各市场区域的指数、新闻搜索词、Prompt 提示等元数据，
供 MarketAnalyzer 按 region 切换 A 股/美股复盘行为。
"""
import os
from dataclasses import dataclass
from typing import List


@dataclass
class MarketProfile:
    """大盘复盘市场区域配置"""

    region: str  # "cn" | "us"
    # 用于判断整体走势的指数代码，cn 用上证 000001，us 用标普 SPX
    mood_index_code: str
    # 新闻搜索关键词
    news_queries: List[str]
    # 指数点评 Prompt 提示语
    prompt_index_hint: str
    # 市场概况是否包含涨跌家数、涨停跌停（A 股有，美股无）
    has_market_stats: bool
    # 市场概况是否包含板块涨跌（A 股有，美股暂无）
    has_sector_rankings: bool


CN_PROFILE = MarketProfile(
    region="cn",
    mood_index_code="000001",
    news_queries=[
        "A股 大盘 复盘",
        "股市 行情 分析",
        "A股 市场 热点 板块",
    ],
    prompt_index_hint="分析上证、深证、创业板等各指数走势特点",
    has_market_stats=True,
    has_sector_rankings=True,
)

US_PROFILE = MarketProfile(
    region="us",
    mood_index_code="SPX",
    news_queries=[
        "美股 大盘",
        "US stock market",
        "S&P 500 NASDAQ",
    ],
    prompt_index_hint="分析标普500、纳斯达克、道指等各指数走势特点",
    has_market_stats=False,
    has_sector_rankings=False,
)

HK_PROFILE = MarketProfile(
    region="hk",
    mood_index_code="HSI",
    news_queries=[
        "港股 大盘 复盘",
        "Hong Kong stock market",
        "恒生指数 行情",
    ],
    prompt_index_hint="分析恒生指数、恒生科技指数、国企指数等各指数走势特点",
    has_market_stats=False,
    has_sector_rankings=False,
)
TW_NEWS_QUERIES = [
    "台股 大盤 盤後",
    "Taiwan stock market",
    "台股 加權指數 走勢",
]

# lite：只取指数 + 新闻（测试 / 快速复盘用）
TW_LITE_PROFILE = MarketProfile(
    region="tw",
    mood_index_code="TWSE",
    news_queries=TW_NEWS_QUERIES,
    prompt_index_hint="分析台股加權指數、櫃買指數等各指數走勢特點",
    has_market_stats=False,
    has_sector_rankings=False,
)

# full：lite + 类股榜（类股来自 TWSE openapi MI_INDEX）。
# 涨跌家数 openapi 无端点，待后续接官网 api 再开 has_market_stats。
TW_FULL_PROFILE = MarketProfile(
    region="tw",
    mood_index_code="TWSE",
    news_queries=TW_NEWS_QUERIES,
    prompt_index_hint="分析台股加權指數、櫃買指數等各指數走勢特點",
    has_market_stats=False,
    has_sector_rankings=True,
)

def get_profile(region: str) -> MarketProfile:
    """根据 region 返回对应的 MarketProfile"""
    if region == "us":
        return US_PROFILE
    if region == "hk":
        return HK_PROFILE
    if region == "tw":
        detail = (os.getenv("MARKET_REVIEW_DETAIL", "lite") or "lite").strip().lower()
        return TW_FULL_PROFILE if detail in ("full", "complete", "detailed") else TW_LITE_PROFILE
    return CN_PROFILE

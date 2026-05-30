# -*- coding: utf-8 -*-
"""
TwIndexFetcher — 台股指数数据源 (lite: 仅大盘指数)

主源:   Fugle MarketData REST (intraday.quote, IX0001 = 加权指数)
兜底:   yfinance (^TWII)

范围 (lite): 只实现 get_main_indices(region="tw")。
台股个股的日线/实时路由刻意还没做, 等接个股阶段再处理。

隔离设计: is_available_for_request 一律返回 False, 使本 fetcher 只参与
get_main_indices (该路径不查 capability), 不污染 get_daily_data 等失败转移链。
"""

import logging
import os
from typing import Optional, List, Dict, Any

from .base import BaseFetcher, DataFetchError
from .tw_index_mapping import (
    TAIEX_FUGLE_SYMBOL,
    TAIEX_YF_SYMBOL,
    TAIEX_INDEX_CODE,
    TAIEX_NAME,
)

logger = logging.getLogger(__name__)


class TwIndexFetcher(BaseFetcher):
    name = "TwIndexFetcher"
    priority = 6  # 仅服务 get_main_indices, 优先级实际不影响结果

    def __init__(self):
        from src.config import get_config
        config = get_config()
        self._api_key = (
            getattr(config, "fugle_api_key", None)
            or os.getenv("FUGLE_API_KEY")
            or ""
        ).strip()
        self._client = None
        if not self._api_key:
            logger.debug("[TwIndex] 未配置 FUGLE_API_KEY, 将仅依赖 yfinance 兜底")

    # 把本 fetcher 关在 get_main_indices 这一条路上 (见模块 docstring)
    def is_available_for_request(self, capability: str = "") -> bool:
        return False

    # BaseFetcher 抽象方法; lite 不做个股日线, 故显式拒绝以暴露误用
    def _fetch_raw_data(self, stock_code, start_date, end_date):
        raise DataFetchError("[TwIndex] lite 阶段不支持个股日线")

    def _normalize_data(self, df, stock_code):
        return df

    # ---- Fugle ----
    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self._api_key:
            return None
        try:
            from fugle_marketdata import RestClient
            self._client = RestClient(api_key=self._api_key)
            return self._client
        except Exception as e:
            logger.warning(f"[TwIndex] Fugle SDK 初始化失败: {e}")
            return None

    @staticmethod
    def _safe_num(v):
        try:
            if v is None:
                return None
            return float(v)
        except (TypeError, ValueError):
            return None

    def get_main_indices(self, region: str = "cn") -> Optional[List[Dict[str, Any]]]:
        if region != "tw":
            return None

        item = self._fetch_taiex_from_fugle()
        if item is not None:
            logger.info("[TwIndex] 加权指数由 Fugle(IX0001) 取得")
            return [item]

        item = self._fetch_taiex_from_yfinance()
        if item is not None:
            logger.info("[TwIndex] 加权指数由 yfinance(^TWII) 兜底取得")
            return [item]

        logger.warning("[TwIndex] 加权指数 Fugle 与 yfinance 两路均失败")
        return None

    def _fetch_taiex_from_fugle(self) -> Optional[Dict[str, Any]]:
        client = self._get_client()
        if client is None:
            return None
        try:
            self.random_sleep(0.2, 0.5)
            data = client.stock.intraday.quote(symbol=TAIEX_FUGLE_SYMBOL)
        except Exception as e:
            logger.warning(f"[TwIndex] Fugle 取 {TAIEX_FUGLE_SYMBOL} 失败: {e}")
            return None
        if not isinstance(data, dict):
            logger.warning(f"[TwIndex] Fugle 返回非预期结构: {type(data)}")
            return None

        current = self._safe_num(data.get("lastPrice"))
        if current is None:
            current = self._safe_num(data.get("closePrice"))
        if current is None:
            return None

        prev_close = self._safe_num(data.get("previousClose"))
        change = self._safe_num(data.get("change"))
        if change is None and prev_close is not None:
            change = round(current - prev_close, 2)
        change_pct = self._safe_num(data.get("changePercent"))
        if change_pct is None and prev_close not in (None, 0):
            change_pct = round((current - prev_close) / prev_close * 100, 2)

        high = self._safe_num(data.get("highPrice"))
        low = self._safe_num(data.get("lowPrice"))
        amplitude = self._safe_num(data.get("amplitude"))
        if amplitude is None and high is not None and low is not None and prev_close not in (None, 0):
            amplitude = round((high - low) / prev_close * 100, 2)

        total = data.get("total") or {}
        return {
            "code": TAIEX_INDEX_CODE,
            "name": TAIEX_NAME,
            "current": current,
            "change": change,
            "change_pct": change_pct,
            "open": self._safe_num(data.get("openPrice")),
            "high": high,
            "low": low,
            "prev_close": prev_close,
            "volume": self._safe_num(total.get("tradeVolume")),
            # 成交金额单位为 元(TWD), 与 A股 fetcher 口径一致;
            # 模板按 region=tw 时 amount/1e8 展示「億元」, 故此处保留原始值不除。
            "amount": self._safe_num(total.get("tradeValue")),
            "amplitude": amplitude,
        }

    # ---- yfinance 兜底 ----
    def _fetch_taiex_from_yfinance(self) -> Optional[Dict[str, Any]]:
        try:
            import yfinance as yf
        except Exception as e:
            logger.warning(f"[TwIndex] yfinance 不可用: {e}")
            return None
        try:
            self.random_sleep(0.2, 0.5)
            hist = yf.Ticker(TAIEX_YF_SYMBOL).history(period="7d", auto_adjust=False)
        except Exception as e:
            logger.warning(f"[TwIndex] yfinance 取 {TAIEX_YF_SYMBOL} 失败: {e}")
            return None
        if hist is None or hist.empty:
            logger.warning("[TwIndex] yfinance 返回空历史")
            return None

        last = hist.iloc[-1]
        current = self._safe_num(last.get("Close"))
        if current is None:
            return None
        if len(hist) >= 2:
            prev_close = self._safe_num(hist.iloc[-2].get("Close"))
        else:
            prev_close = self._safe_num(last.get("Open"))

        change = round(current - prev_close, 2) if prev_close is not None else None
        change_pct = (
            round((current - prev_close) / prev_close * 100, 2)
            if prev_close not in (None, 0) else None
        )
        high = self._safe_num(last.get("High"))
        low = self._safe_num(last.get("Low"))
        amplitude = (
            round((high - low) / prev_close * 100, 2)
            if (high is not None and low is not None and prev_close not in (None, 0)) else None
        )

        return {
            "code": TAIEX_INDEX_CODE,
            "name": TAIEX_NAME,
            "current": current,
            "change": change,
            "change_pct": change_pct,
            "open": self._safe_num(last.get("Open")),
            "high": high,
            "low": low,
            "prev_close": prev_close,
            "volume": self._safe_num(last.get("Volume")),
            "amount": None,  # yfinance 不提供成交金额
            "amplitude": amplitude,
        }

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
from typing import Optional, List, Dict, Any, Tuple

from .base import BaseFetcher, DataFetchError
from .tw_index_mapping import (
    TAIEX_FUGLE_SYMBOL,
    TAIEX_YF_SYMBOL,
    TAIEX_INDEX_CODE,
    TAIEX_NAME,
    TWSE_MI_INDEX_URL,
    TWSE_MI_INDEX_MS_URL,
    TWSE_COMPANY_LIST_URL,
    TW_CATEGORY_INDEX_SUFFIX,
    tw_category_short_name,
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
        self._tw_name_map = None  # 台股上市公司名录缓存 (代号 -> 中文简称)
        if not self._api_key:
            logger.debug("[TwIndex] 未配置 FUGLE_API_KEY, 将仅依赖 yfinance 兜底")

    # 仅对外开放「台股个股名称」能力; 大盘复盘 (main_indices/sector_rankings) 的 manager
    # 循环不查 capability, 故仍可用; daily_data/realtime 等查 capability 的路径保持隔离。
    def is_available_for_request(self, capability: str = "") -> bool:
        return capability == "stock_name"

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
            self._log_fetched("Fugle(IX0001)", item)
            return [item]

        item = self._fetch_taiex_from_yfinance()
        if item is not None:
            self._log_fetched("yfinance(^TWII)", item)
            return [item]

        logger.warning("[TwIndex] 加权指数 Fugle 与 yfinance 两路均失败")
        return None

    @staticmethod
    def _log_fetched(source: str, item: Dict[str, Any]) -> None:
        # 打印原始字段便于核对 Fugle 字段映射与量级 (amount 单位为元 TWD)
        logger.info(
            "[TwIndex] 加权指数由 %s 取得: current=%s change=%s change_pct=%s%% "
            "open=%s high=%s low=%s amplitude=%s%% volume=%s amount(元)=%s",
            source,
            item.get("current"), item.get("change"), item.get("change_pct"),
            item.get("open"), item.get("high"), item.get("low"),
            item.get("amplitude"), item.get("volume"), item.get("amount"),
        )

    # ---- 类股榜 (full): TWSE openapi MI_INDEX ----
    def get_sector_rankings(
        self, n: int = 5, region: str = "cn"
    ) -> Optional[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
        if region != "tw":
            return None
        rows = self._fetch_twse_category_indices()
        if not rows:
            logger.warning("[TwIndex] 类股指数 (TWSE MI_INDEX) 获取为空")
            return None
        top = sorted(rows, key=lambda x: x["change_pct"], reverse=True)[:n]
        bottom = sorted(rows, key=lambda x: x["change_pct"])[:n]
        logger.info(
            "[TwIndex] 类股榜由 TWSE openapi(MI_INDEX) 取得: %d 个类指数, 领涨=%s 领跌=%s",
            len(rows),
            [s["name"] for s in top], [s["name"] for s in bottom],
        )
        return top, bottom

    # ---- 涨跌家数 + 成交额 (full): 官网盘后 MI_INDEX type=MS ----
    def get_market_stats(self, region: str = "cn") -> Optional[Dict[str, Any]]:
        if region != "tw":
            return None
        date_str = self._tw_effective_date()
        if not date_str:
            return None
        data = self._twse_get_json(
            TWSE_MI_INDEX_MS_URL.format(date=date_str), f"TWSE 漲跌家數({date_str})"
        )
        if not isinstance(data, dict) or data.get("stat") != "OK":
            stat = data.get("stat") if isinstance(data, dict) else type(data).__name__
            logger.warning(f"[TwIndex] TWSE 漲跌家數 返回非 OK: {stat}")
            return None
        tables = data.get("tables") or []
        breadth = self._parse_tw_breadth(tables)
        if breadth is None:
            logger.warning("[TwIndex] TWSE 漲跌家數 未找到漲跌證券數合計表")
            return None
        breadth["total_amount"] = self._parse_tw_turnover(tables)
        logger.info(
            "[TwIndex] 涨跌家数由 TWSE(%s) 取得: 涨%s(涨停%s) 跌%s(跌停%s) 平%s 成交额%.0f億",
            date_str, breadth["up_count"], breadth["limit_up_count"],
            breadth["down_count"], breadth["limit_down_count"],
            breadth["flat_count"], breadth["total_amount"],
        )
        return breadth

    @staticmethod
    def _tw_effective_date() -> Optional[str]:
        try:
            from src.core.trading_calendar import get_effective_trading_date
            return get_effective_trading_date("tw").strftime("%Y%m%d")
        except Exception as e:
            logger.warning(f"[TwIndex] 取台股最近交易日失败: {e}")
            return None

    @staticmethod
    def _parse_tw_count(value: Any):
        """'9,879(419)' -> (9879, 419); '805' -> (805, 0)。"""
        import re
        s = str(value).replace(",", "").strip()
        m = re.match(r"(\d+)(?:\((\d+)\))?", s)
        if not m:
            return None, 0
        return int(m.group(1)), (int(m.group(2)) if m.group(2) else 0)

    def _parse_tw_breadth(self, tables) -> Optional[Dict[str, Any]]:
        target = next(
            (t for t in tables
             if isinstance(t, dict) and "漲跌證券數" in str(t.get("title", ""))),
            None,
        )
        if target is None:
            return None
        fields = target.get("fields") or []
        # 取「股票」列 (个股口径), 取不到退用最后一列
        col = fields.index("股票") if "股票" in fields else (len(fields) - 1 if fields else 2)
        up = down = flat = limit_up = limit_down = 0
        for row in target.get("data") or []:
            if not isinstance(row, list) or len(row) <= col:
                continue
            label = str(row[0])
            main, paren = self._parse_tw_count(row[col])
            if main is None:
                continue
            if label.startswith("上漲"):
                up, limit_up = main, paren
            elif label.startswith("下跌"):
                down, limit_down = main, paren
            elif label.startswith("持平"):
                flat = main
        return {
            "up_count": up,
            "down_count": down,
            "flat_count": flat,
            "limit_up_count": limit_up,
            "limit_down_count": limit_down,
        }

    def _parse_tw_turnover(self, tables) -> float:
        """大盤統計資訊: 取「一般股票」成交金額(元) 折算億元。"""
        for t in tables:
            if not isinstance(t, dict):
                continue
            fields = t.get("fields") or []
            if "成交金額(元)" not in fields:
                continue
            amt_col = fields.index("成交金額(元)")
            for row in t.get("data") or []:
                if not isinstance(row, list) or len(row) <= amt_col:
                    continue
                if "一般股票" in str(row[0]):
                    amt = self._safe_num(str(row[amt_col]).replace(",", ""))
                    if amt is not None:
                        return round(amt / 1e8, 0)
        return 0.0

    def _twse_get_json(self, url: str, label: str, retries: int = 2, timeout: int = 15):
        """带重试地请求 TWSE openapi JSON（openapi 偶发连接超时，单次失败会丢数据）。"""
        try:
            import requests
        except Exception as e:
            logger.warning(f"[TwIndex] requests 不可用: {e}")
            return None
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                self.random_sleep(0.2, 0.5)
                resp = requests.get(
                    url,
                    timeout=timeout,
                    headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"},
                )
                resp.raise_for_status()
                return resp.json()
            except Exception as e:
                last_err = e
                logger.warning(f"[TwIndex] {label} 第 {attempt}/{retries} 次取得失败: {e}")
        logger.warning(f"[TwIndex] {label} 重试耗尽: {last_err}")
        return None

    def _fetch_twse_category_indices(self) -> Optional[List[Dict[str, Any]]]:
        data = self._twse_get_json(TWSE_MI_INDEX_URL, "TWSE MI_INDEX")
        if not isinstance(data, list):
            if data is not None:
                logger.warning(f"[TwIndex] TWSE MI_INDEX 返回非预期结构: {type(data)}")
            return None

        results: List[Dict[str, Any]] = []
        for row in data:
            if not isinstance(row, dict):
                continue
            name = (row.get("指數") or "").strip()
            if not name.endswith(TW_CATEGORY_INDEX_SUFFIX):
                continue
            pct = self._safe_num((row.get("漲跌百分比") or "").replace(",", ""))
            if pct is None:
                continue
            # 漲跌百分比 为无符号字串, 方向看「漲跌」字段: '-'/'－' 为跌, 其余('+'/'X'/空)为涨或平
            sign = str(row.get("漲跌", "")).strip()
            pct = -abs(pct) if sign in ("-", "－") else abs(pct)
            results.append({
                "name": tw_category_short_name(name),
                "change_pct": round(pct, 2),
            })
        return results or None

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

    # ---- 台股个股中文名 (TWSE 上市公司名录) ----
    def get_stock_name(self, stock_code: str) -> Optional[str]:
        code = (stock_code or "").strip().upper()
        if code.endswith(".TW") or code.endswith(".TWO"):
            digits = code.rsplit(".", 1)[0]
        elif code.isdigit():
            digits = code
        else:
            return None
        if not digits.isdigit():
            return None
        name_map = self._get_tw_name_map()
        return name_map.get(digits) if name_map else None

    def _get_tw_name_map(self) -> Dict[str, str]:
        if self._tw_name_map is not None:
            return self._tw_name_map
        result: Dict[str, str] = {}
        data = self._twse_get_json(TWSE_COMPANY_LIST_URL, "TWSE 上市公司名录")
        if isinstance(data, list):
            for row in data:
                if not isinstance(row, dict):
                    continue
                c = str(row.get("公司代號", "")).strip()
                nm = str(row.get("公司簡稱", "")).strip()
                if c and nm:
                    result[c] = nm
        logger.info("[TwIndex] 载入 TWSE 上市公司名录 %d 笔", len(result))
        self._tw_name_map = result
        return result

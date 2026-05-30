# -*- coding: utf-8 -*-
"""
台股指数代码映射 (lite 阶段仅指数)。

Fugle:    加权指数 IX0001, 柜买指数 IX0043 (个股/指数同一 intraday.quote 接口)
yfinance: 加权指数 ^TWII (柜买无好用代码, lite 先只做加权指数)
"""

# Fugle symbols
TAIEX_FUGLE_SYMBOL = "IX0001"   # 加权指数 (TAIEX)
OTC_FUGLE_SYMBOL = "IX0043"     # 柜买指数 (OTC), lite 暂不用

# yfinance fallback
TAIEX_YF_SYMBOL = "^TWII"

# 内部统一代码: 加权指数那条必须等于 "TWSE", 对上 TW profile 的 mood_index_code
TAIEX_INDEX_CODE = "TWSE"
TAIEX_NAME = "加权指数"
OTC_INDEX_CODE = "OTC"
OTC_NAME = "柜买指数"


def is_tw_stock_code(code: str) -> bool:
    """
    判定是否为台股个股代码。

    可靠信号:
    - 带 .TW / .TWO 后缀 (如 2330.TW, 5347.TWO)
    - 裸 4 位数字 (台股上市个股, 与 A股 6 位 / 港股 5 位不冲突)

    注意: 台股 ETF 可能是 5 到 6 位 (如 00878, 006208), 裸码会与港股(5)/A股(6)
    冲突, 这类必须带 .TW/.TWO 后缀才能被识别。lite 阶段(只取指数)不依赖本函数,
    它是给以后接台股个股时用的, 届时需配合 normalize_stock_code 一起消歧。
    """
    if not code:
        return False
    c = code.strip().upper()
    if c.endswith(".TW") or c.endswith(".TWO"):
        base = c.rsplit(".", 1)[0]
        return base.isdigit() and 4 <= len(base) <= 6
    if c.isdigit() and len(c) == 4:
        return True
    return False


# ---- 类股榜 (full): TWSE 开放 API ----
# 每日收盘行情-大盘统计资讯, 返回各类指数 {日期, 指數, 收盤指數, 漲跌, 漲跌點數, 漲跌百分比}
# 注意: openapi 只提供前一交易日数据, 不含涨跌家数。
TWSE_MI_INDEX_URL = "https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX"

# 上市公司名录 (公司代號/公司簡稱/公司名稱), 用于台股个股中文简称 (2330 -> 台積電)
TWSE_COMPANY_LIST_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"

# 台股产业类指数一律以「類指數」结尾 (半導體類指數/金融保險類指數/航運類指數...);
# 主题/ESG/规模指数 (寶島股價指數/臺灣50指數/臺灣AI供應鏈聯盟指數) 不以此结尾, 天然排除。
TW_CATEGORY_INDEX_SUFFIX = "類指數"


def tw_category_short_name(index_name: str) -> str:
    """类指数显示简称: 半導體類指數 -> 半導體; 取不到则原样返回。"""
    if not index_name:
        return index_name
    name = index_name.strip()
    if name.endswith(TW_CATEGORY_INDEX_SUFFIX):
        return name[: -len(TW_CATEGORY_INDEX_SUFFIX)].strip() or name
    return name

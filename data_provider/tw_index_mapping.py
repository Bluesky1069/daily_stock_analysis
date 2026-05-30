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

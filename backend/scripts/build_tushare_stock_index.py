"""Build bundled Tushare A-share stock official API index for TIA full scan.

Source alignment: https://tushare.pro/document/2 (股票 + A股行情/财务/参考/特色)
Run: python scripts/build_tushare_stock_index.py
"""

from __future__ import annotations

import json
from pathlib import Path

# (api_name, doc_id, category, probe_category, min_points, label)
STOCK_A_APIS: list[tuple[str, int, str, str, int, str]] = [
    # 基础
    ("stock_basic", 25, "基础", "list_basic", 120, "股票列表"),
    ("trade_cal", 26, "基础", "trade_date", 120, "交易日历"),
    ("namechange", 100, "基础", "list_limit", 120, "股票曾用名"),
    # hs_const doc_id=35 removed — document/2 page 404, not on current sidebar menu
    ("stock_company", 112, "基础", "ts_code", 120, "上市公司基本信息"),
    ("stk_managers", 193, "基础", "ts_code", 120, "上市公司管理层"),
    ("stk_rewards", 194, "基础", "ts_code", 120, "管理层薪酬持股"),
    ("new_share", 123, "基础", "list_limit", 120, "IPO新股"),
    ("bse_mapping", 375, "基础", "list_limit", 120, "北交所代码对照"),
    ("st_list", 397, "基础", "list_limit", 120, "ST股票列表"),
    ("stock_hsgt", 398, "基础", "list_limit", 120, "沪深港通股票列表"),
    # 行情
    ("daily", 27, "行情", "ts_code_date_range", 120, "日线"),
    ("weekly", 144, "行情", "ts_code_date_range", 2000, "周线"),
    ("monthly", 29, "行情", "ts_code_date_range", 120, "月线"),
    ("pro_bar", 30, "行情", "ts_code_date_range", 120, "复权行情"),
    ("adj_factor", 31, "行情", "ts_code_date_range", 120, "复权因子"),
    ("suspend_d", 32, "行情", "ts_code_date_range", 120, "停复牌"),
    ("daily_basic", 32, "行情", "ts_code_date_range", 120, "每日指标"),
    ("stk_limit", 183, "行情", "trade_date", 120, "涨跌停价格"),
    ("stk_auction_o", 353, "行情", "trade_date", 120, "开盘集合竞价"),
    ("stk_auction_c", 354, "行情", "trade_date", 120, "收盘集合竞价"),
    ("stk_factor", 296, "行情", "ts_code_date_range", 5000, "技术面因子"),
    ("stk_factor_pro", 328, "行情", "ts_code_date_range", 5000, "技术面因子Pro"),
    # 财务
    ("income", 33, "财务", "period_financial", 600, "利润表"),
    ("balancesheet", 36, "财务", "period_financial", 600, "资产负债表"),
    ("cashflow", 44, "财务", "period_financial", 600, "现金流量表"),
    ("forecast", 45, "财务", "period_financial", 600, "业绩预告"),
    ("express", 46, "财务", "period_financial", 600, "业绩快报"),
    ("dividend", 103, "财务", "ts_code", 120, "分红送股"),
    ("fina_indicator", 48, "财务", "period_financial", 600, "财务指标"),
    ("fina_audit", 47, "财务", "period_financial", 600, "审计意见"),
    ("fina_mainbz", 81, "财务", "period_financial", 600, "主营业务构成"),
    ("disclosure_date", 162, "财务", "ts_code", 120, "财报披露计划"),
    # 参考/股东
    ("top10_holders", 61, "参考", "ts_code", 120, "前十大股东"),
    ("top10_floatholders", 62, "参考", "ts_code", 120, "前十大流通股东"),
    ("pledge_stat", 110, "参考", "ts_code", 120, "股权质押统计"),
    ("pledge_detail", 111, "参考", "ts_code", 120, "股权质押明细"),
    ("repurchase", 124, "参考", "ts_code", 120, "股票回购"),
    ("share_float", 160, "参考", "ts_code", 120, "限售股解禁"),
    ("block_trade", 161, "参考", "trade_date", 120, "大宗交易"),
    ("stk_holdernumber", 166, "参考", "ts_code", 120, "股东人数"),
    ("stk_holdertrade", 175, "参考", "ts_code", 120, "股东增减持"),
    # 资金流向/两融
    ("moneyflow", 55, "资金", "ts_code_date_range", 2000, "个股资金流向"),
    ("moneyflow_hsgt", 56, "资金", "trade_date", 2000, "沪深港通资金"),
    ("margin", 58, "两融", "trade_date", 2000, "融资融券汇总"),
    ("margin_detail", 59, "两融", "trade_date", 2000, "融资融券明细"),
    ("margin_target", 326, "两融", "list_limit", 120, "融资融券标的"),
    # 龙虎榜/打板
    ("top_list", 106, "特色", "trade_date", 2000, "龙虎榜每日统计"),
    ("top_inst", 107, "特色", "trade_date", 5000, "龙虎榜机构"),
    ("limit_list", 356, "特色", "trade_date", 2000, "涨跌停列表"),
    ("limit_list_d", 357, "特色", "trade_date", 2000, "涨跌停明细"),
    ("hm_list", 311, "特色", "list_limit", 2000, "游资名录"),
    ("hm_detail", 312, "特色", "trade_date", 2000, "游资明细"),
    ("cyq_perf", 293, "特色", "ts_code_date_range", 5000, "筹码及胜率"),
    ("cyq_chips", 294, "特色", "ts_code_date_range", 5000, "筹码分布"),
    # 港股通
    ("ggt_top10", 73, "港股通", "trade_date", 2000, "港股通十大成交"),
    ("hsgt_top10", 74, "港股通", "trade_date", 2000, "沪股通十大成交"),
    ("ggt_daily", 75, "港股通", "trade_date", 2000, "港股通每日成交"),
    ("hk_hold", 274, "港股通", "ts_code", 2000, "中央结算持股"),
    # 概念/热榜
    ("concept", 71, "概念", "list_limit", 120, "概念分类"),
    ("concept_detail", 72, "概念", "ts_code", 120, "概念成分"),
    ("ths_hot", 259, "热榜", "trade_date", 2000, "同花顺热榜"),
    ("dc_hot", 321, "热榜", "trade_date", 2000, "东财热榜"),
    # 研报/调研
    ("broker_recommend", 267, "研报", "ts_code", 120, "券商金股"),
    ("report_rc", 77, "研报", "ts_code", 120, "研报评级"),
    ("stk_surv", 275, "调研", "ts_code", 120, "机构调研"),
    # 指数成分(常用)
    ("index_member", 61, "指数", "list_limit", 120, "指数成分"),
    ("index_weight", 61, "指数", "trade_date", 120, "指数权重"),
]


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "app" / "catalog" / "providers" / "tushare_stock_official_apis.json"
    apis = []
    seen: set[str] = set()
    for api, doc_id, cat, probe, pts, label in STOCK_A_APIS:
        if api in seen:
            continue
        seen.add(api)
        apis.append(
            {
                "api": api,
                "doc_id": doc_id,
                "category": cat,
                "probe_category": probe,
                "min_points": pts,
                "label": label,
                "scope": "stock_a",
            }
        )
    payload = {
        "provider": "tushare",
        "scope": "stock_a",
        "version": "2025-06-stock-a",
        "source": "bundled",
        "description": "Tushare Pro A股/股票专题接口快照，对齐 document/2 股票与相关专题",
        "apis": apis,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(apis)} APIs to {out}")


if __name__ == "__main__":
    main()

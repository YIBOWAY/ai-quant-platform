"""Fixed public-method adaptations, independent of the executable strategy registry.

These static lists were transcribed from the existing universe registry before
evaluating the profiles. They deliberately do not follow later registry changes.
"""

from copy import deepcopy

TECHNOLOGY = ("AAPL", "MSFT", "NVDA", "AMD", "GOOGL", "META", "AVGO", "ORCL", "CRM")
STOCKS = TECHNOLOGY + (
    "LMT",
    "RTX",
    "NOC",
    "GD",
    "HII",
    "LHX",
    "BA",
    "UNH",
    "JNJ",
    "PFE",
    "MRK",
    "ABBV",
    "TMO",
    "MDT",
    "AMGN",
)
ASSETS = ("SPY", "EFA", "IEF", "VNQ", "DBC")
_LABELS = {
    "AAPL": "苹果",
    "MSFT": "微软",
    "NVDA": "英伟达",
    "AMD": "AMD",
    "GOOGL": "Alphabet",
    "META": "Meta",
    "AVGO": "博通",
    "ORCL": "甲骨文",
    "CRM": "Salesforce",
    "LMT": "洛克希德马丁",
    "RTX": "RTX",
    "NOC": "诺斯罗普格鲁曼",
    "GD": "通用动力",
    "HII": "亨廷顿英格尔斯",
    "LHX": "L3Harris",
    "BA": "波音",
    "UNH": "联合健康",
    "JNJ": "强生",
    "PFE": "辉瑞",
    "MRK": "默沙东",
    "ABBV": "艾伯维",
    "TMO": "赛默飞",
    "MDT": "美敦力",
    "AMGN": "安进",
    "SPY": "标普500 ETF",
    "QQQ": "纳斯达克100 ETF",
    "EFA": "发达市场除美加 ETF",
    "IEF": "美国7–10年国债 ETF",
    "VNQ": "美国房地产 ETF",
    "DBC": "商品期货 ETF",
    "SHY": "美国1–3年国债 ETF",
}
_MOM = {
    "title": "Kenneth French: Monthly Momentum Factor",
    "url": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/det_mom_factor.html",
}
_REV = {
    "title": "Kenneth French: Monthly Short-Term Reversal Factor",
    "url": "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/det_st_rev_factor.html",
}
_VOL = {
    "title": "S&P Low Volatility Indices Methodology",
    "url": "https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-low-volatility-indices.pdf",
}
_ROTATION = {
    "title": "Meb Faber: Cross-Market Momentum (2008)",
    "url": "https://mebfaber.com/2008/08/07/alpha-persistence-a-simple-momentum-system-for-beating-the-market/",
}
_TREND = {
    "title": "Meb Faber: A Quantitative Approach to Tactical Asset Allocation, revisited",
    "url": "https://mebfaber.com/2017/12/13/episode-86-quantitative-approach-tactical-asset-allocation/",
}
_R2 = {
    "title": "Larry Connors: The Improved R2 Strategy (2007)",
    "url": "https://tradingmarkets.com/recent/the_improved_r2_strategy_84_correct_with_just_6_rules_-674361",
}
_COMMON = [
    "固定参数的历史研究；2018–2021/2022–2024/2025起只是时间分区，不宣称历史完全未被查看。",
    "仅用已知收盘生成信号，下一真实交易日开盘成交；与作者同日收盘成交存在执行偏离。",
    "Futu 1d QFQ不保证含分红再投资的总回报；无外汇转换，所有标的采用美元报价。",
    "无杠杆、无做空；单边佣金1bp、滑点5bp，现金利息为0，未模拟税收和额外冲击。",
    "价格或完整形成窗口不足时不入选；历史缺失和上市前区间不作价格填充。",
    "排序组合可用标的不足Top N时，策略与同池对照共同持有现金，直至窗口完整。",
]
_STATIC = (
    "2026-09-07从当前technology/defense/healthcare registry固定的现存股票名单，"
    "排除XLV；存在幸存者与静态成员偏差，不代表当时全市场或历史指数成分。"
)


def _profile(
    identifier,
    name,
    family,
    symbols,
    benchmark,
    *,
    formation,
    rules,
    sources,
    limitations=(),
    defensive=False,
    top_n=None,
):
    universe = list(symbols)
    traded = universe + (["SHY"] if defensive else [])
    return {
        "id": identifier,
        "name": name,
        "family": family,
        "description": name,
        "symbols": traded,
        "symbol_labels": {s: _LABELS[s] for s in traded},
        "benchmark_symbol": benchmark,
        "peer_symbols": universe,
        "rebalance": "daily_event" if family == "rsi_reversion" else "monthly",
        "formation": formation,
        "holding": "RSI2>75后次日开盘退出，其他日期不调仓"
        if family == "rsi_reversion"
        else "下月首个真实交易日开盘调仓，持有至下一月调仓；期末按真实收盘盯市",
        "rules": rules,
        "sources": sources,
        "limitations": [*_COMMON, *limitations],
        "top_n": top_n,
        "defensive_symbol": "SHY" if defensive else None,
        "universe_snapshot_date": "2026-09-07",
        "membership_mode": "static_snapshot",
    }


def list_study_profiles() -> list[dict]:
    """Return independent JSON-ready copies; no registry, provider or storage effects."""
    return deepcopy(_PROFILES)


_PROFILES = [
    _profile(
        "technology_momentum_12_2",
        "科技9股：12–2月动量 Top3",
        "stock_momentum",
        TECHNOLOGY,
        "QQQ",
        formation="持有月t累计t−12至t−2共11个月，跳过t−1",
        rules=["按12–2月价格动量从高到低选择3只等权；每月重排，不设正收益门槛。"],
        sources=[_MOM],
        limitations=[
            _STATIC,
            "French原版为规模分组、价值加权多空；本方案为固定股票池只做多等权改编。",
        ],
        top_n=3,
    ),
    _profile(
        "stocks_momentum_12_2",
        "跨行业24股：12–2月动量 Top5",
        "stock_momentum",
        STOCKS,
        "SPY",
        formation="持有月t累计t−12至t−2共11个月，跳过t−1",
        rules=["按12–2月价格动量从高到低选择5只等权；每月重排，不设正收益门槛。"],
        sources=[_MOM],
        limitations=[
            _STATIC,
            "French原版为规模分组、价值加权多空；本方案为固定股票池只做多等权改编。",
        ],
        top_n=5,
    ),
    _profile(
        "stocks_price_multifactor",
        "跨行业24股：价格三因子 Top5",
        "price_multifactor",
        STOCKS,
        "SPY",
        formation="12–2月动量、252日日收益标准差、最近1个月短反转",
        rules=[
            "三项各自横截面百分位rank后等权平均；动量高、波动低、最近1月收益低更优。",
            "三个形成窗口均完整才参与排名；选择总分前5只等权，分数并列按symbol排序。",
        ],
        sources=[_MOM, _VOL, _REV],
        limitations=[
            _STATIC,
            "价格三因子合成为本项目固定改编，不是原论文组合，也不是value/quality基本面因子。",
            "S&P低波原方法使用低波股票及波动率倒数权重；French反转原版为规模分组多空。",
        ],
        top_n=5,
    ),
    _profile(
        "etf_relative_momentum",
        "五资产ETF：3/6/12月动量 Top3",
        "asset_momentum",
        ASSETS,
        "SPY",
        formation="近3、6、12个月价格收益算术平均，不跳月",
        rules=["固定五类ETF内选综合动量前3，各1/3，每月调仓，无正收益门槛。"],
        sources=[_ROTATION],
        limitations=[
            "ETF为原资产类别的可交易代理；上市前不拼接指数回报，QFQ价格版不等同原文总回报。"
        ],
        top_n=3,
    ),
    _profile(
        "etf_relative_momentum_trend",
        "五资产ETF：动量 Top3 + 10月趋势防守",
        "asset_momentum",
        ASSETS,
        "SPY",
        formation="近3、6、12个月价格收益算术平均，加10个月末收盘均线",
        rules=[
            "先选动量前3；入选ETF月末收盘>自身10月均线则保留1/3，否则该份额转SHY。",
            "不重新分配给其余风险资产；SHY自身不再应用趋势过滤。",
        ],
        sources=[_ROTATION, _TREND],
        limitations=["动量加趋势为组合改编；原轮动持续满仓，原趋势防守为现金/国库券，此处用SHY。"],
        defensive=True,
        top_n=3,
    ),
]
for _symbol in ("SPY", "QQQ"):
    _PROFILES.append(
        _profile(
            f"{_symbol.lower()}_sma10",
            f"{_symbol}：10月均线趋势 / SHY",
            "index_trend",
            (_symbol,),
            _symbol,
            formation="10个完整月末收盘的简单平均，不跳月",
            rules=[f"月末{_symbol}收盘>10月均线则持有{_symbol}，否则持有SHY，每月检查。"],
            sources=[_TREND],
            limitations=[
                "ETF和SHY替代原研究的指数总回报与国库券现金。",
                *(["QQQ为从宽基趋势方法扩展的纳斯达克100代理改编。"] if _symbol == "QQQ" else []),
            ],
            defensive=True,
        )
    )
for _symbol in ("SPY", "QQQ"):
    _PROFILES.append(
        _profile(
            f"{_symbol.lower()}_r2",
            f"{_symbol}：Connors Improved R2 短期回归",
            "rsi_reversion",
            (_symbol,),
            _symbol,
            formation="Wilder RSI(2)，SMA200，连续3个交易日RSI",
            rules=[
                "空仓时：收盘>SMA200，RSI[t−2]<65且RSI[t−2]>RSI[t−1]>RSI[t]，次日开盘买入。",
                "持有时RSI2>75，次日开盘全部退出；其余时间保持原持仓，空仓资金不计息。",
            ],
            sources=[_R2],
            limitations=[
                "原作者对SPX/SPY定义六规则；此处以ETF自身价格计算指标。",
                "原文未完整披露交易费用；本结果显式扣费且采用next-open，不引用原文胜率作为本方案表现。",
                *(["QQQ属于额外指数代理改编，非原作者SPX结果。"] if _symbol == "QQQ" else []),
            ],
        )
    )

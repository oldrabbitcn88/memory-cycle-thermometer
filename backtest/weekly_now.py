#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""最近三周实测：用真实周度现货价 + 当季季度指标，按新口径出分。"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import scoring as sc

# 真实现货读数（TrendForce 主流 DDR4 1Gx8 3200MT/s，$/颗）
SPOT = [("2026-06-30", 36.00), ("2026-07-07", 37.14), ("2026-07-15", 39.80), ("2026-07-21", 41.10)]
# 当季（3Q26）季度指标——周频内不变，标注数据基准日
QUARTERLY = {
  "capex":     {"yoy_pct": 40, "new_fabs": 4, "new_entrant": True, "asof": "2026-07-06"},
  "inventory": {"weeks": 3.5, "lta": True, "sellout": True, "asof": "2026-07-08"},
  "demand":    {"doubt": True, "asof": "2026-07-03"},
  "narrative": {"years_out": 4.0, "bears": 1, "mega": True, "asof": "2026-07-12"},
}
ETF = {"price": 47.62, "high": 81.34, "asof": "2026-07-29"}

rows, streak, phase, ps, pm = [], [0]*5, "扩张期", None, None
# 用季度回测末态初始化慢变量连亮计数（②⑤已长期亮灯）
streak = [0, 12, 4, 0, 4]

for i in range(1, len(SPOT)):
    d0, p0 = SPOT[i-1]; d1, p1 = SPOT[i]
    wow = (p1/p0 - 1) * 100
    wd = 0  # 连续下跌周数：本段全为上涨
    m = [
        {"premium_pct": 120.0, "wow_pct": round(wow,2), "weeks_down": wd},  # 溢价远高于合约（合约绝对值未公开，取保守下限）
        QUARTERLY["capex"], QUARTERLY["inventory"], QUARTERLY["demand"], QUARTERLY["narrative"],
    ]
    s = sc.score_all(m)
    streak = sc.update_streak(streak, s)
    phase = sc.next_phase(phase, s)
    r = sc.compose(s, sc.decay_factors(streak), phase)
    b = sc.bottom_score(s, ps, m, pm)
    rows.append({"date": d1, "spot": p1, "wow": round(wow,2), "s": s,
                 "top": r["total"], "bottom": b["total"], "phase": phase,
                 "n50": r["n50"], "n75": r["n75"], "trig": r["triggers"]})
    ps, pm = s, m

eq = sc.equity_anchor(ETF["price"], ETF["high"], spot_at_record=True)
print(f"{'日期':12}{'现货$':>8}{'周环比':>8} {'①':>4}{'②':>4}{'③':>4}{'④':>4}{'⑤':>4} {'顶温':>5}{'底温':>5} {'灯':>5} 相位")
print("-"*82)
for r in rows:
    print(f"{r['date']:12}{r['spot']:8.2f}{r['wow']:7.2f}% {r['s'][0]:4d}{r['s'][1]:4d}{r['s'][2]:4d}"
          f"{r['s'][3]:4d}{r['s'][4]:4d} {r['top']:5d}{r['bottom']:5d} {str(r['n50'])+'/'+str(r['n75']):>5} {r['phase']}")
print(f"\n触发器状态: {rows[-1]['trig'] if rows[-1]['trig'] else '未触发'}")
print(f"市场定价锚: DRAM ETF ${ETF['price']} vs 高点 ${ETF['high']} = {eq['drawdown_pct']}% | "
      f"背离告警: {'★是★' if eq['alert'] else '否'}")
print(f"  {eq['note']}")
json.dump({"weekly": rows, "equity": {**ETF, **eq}},
          open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "weekly_now.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

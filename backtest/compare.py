#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""口径对比：5个先验候选方案，2018周期定参 / 2022周期样本外验证。
不做自由网格搜索——24期数据撑不起那么多自由度，搜出来的只会是过拟合。"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import scoring as sc

HERE = os.path.dirname(os.path.abspath(__file__))
QS = json.load(open(os.path.join(HERE, "metrics_quarterly.json"), encoding="utf-8"))["quarters"]

# ---- 周期真值（公开记录）----
PEAKS   = {"2018Q3", "2022Q1"}          # 合约价见顶
BOTTOMS = {"2019Q4", "2023Q3"}          # 周期底部
UPTREND = {"2017Q1","2017Q2","2017Q3","2017Q4","2021Q1","2021Q2",
           "2024Q1","2024Q2","2024Q3","2024Q4","2025Q1","2025Q2"}  # 明确上行期，报顶=误报

IDX = {x["q"]: i for i, x in enumerate(QS)}

# ---- 5个候选口径（先验假设，非拟合产物）----
CONFIGS = {
  "A 原始v2":     dict(w=[.25,.20,.20,.20,.15], trig=False, decay=False, phase=False, thr=75, n50=99, n75=99),
  "B v3标准":     dict(w=[.25,.20,.20,.20,.15], trig=True,  decay=True,  phase=True,  thr=75, n50=4,  n75=3),
  "C 需求加权":   dict(w=[.25,.15,.15,.30,.15], trig=True,  decay=True,  phase=True,  thr=75, n50=4,  n75=3),
  "D 组合确认":   dict(w=[.20,.20,.20,.20,.20], trig=True,  decay=True,  phase=True,  thr=70, n50=3,  n75=2),
  "E 价格主导":   dict(w=[.40,.15,.15,.20,.10], trig=True,  decay=True,  phase=True,  thr=70, n50=4,  n75=3),
}

def run(cfg):
    out, streak, phase, prev_s, prev_m = [], [0]*5, "扩张期", None, None
    for item in QS:
        m = item["m"]
        for i, mm in enumerate(m):
            mm.setdefault("production_cut", item.get("production_cut", False))
        s = sc.score_all(m)
        streak = sc.update_streak(streak, s)
        f = sc.decay_factors(streak) if cfg["decay"] else [1.0]*5
        eff = [s[i]*f[i] for i in range(5)]
        total = int(round(sum(eff[i]*cfg["w"][i] for i in range(5))))
        n50, n75 = sum(1 for x in s if x >= 50), sum(1 for x in s if x >= 75)
        phase = sc.next_phase(phase, s) if cfg["phase"] else "扩张期"

        warn = False
        if phase not in ("下行期", "筑底期"):
            if cfg["trig"] and (s[0] >= cfg["thr"] or n75 >= cfg["n75"] or n50 >= cfg["n50"]
                                or (s[0] >= 50 and s[3] >= 50)):
                warn = True
            elif total >= 70:
                warn = True
        b = sc.bottom_score(s, prev_s, m, prev_m)
        out.append({"q": item["q"], "s": s, "top": total, "warn": warn,
                    "phase": phase, "bottom": b["total"]})
        prev_s, prev_m = s, m
    return out

def evaluate(rows):
    r = {x["q"]: x for x in rows}
    res = {}
    for peak in sorted(PEAKS):
        pi = IDX[peak]
        lead = None
        for j in range(pi, -1, -1):
            if rows[j]["warn"]:
                lead = pi - j
            elif lead is not None:
                break
        res[f"顶{peak}"] = lead
    for bot in sorted(BOTTOMS):
        res[f"底{bot}"] = r[bot]["bottom"]
    res["上行期误报"] = sum(1 for q in UPTREND if r[q]["warn"])
    return res

print(f"{'口径':12} {'2018顶提前':>10} {'2022顶提前':>10} {'2019Q4底温':>11} {'2023Q3底温':>11} {'上行误报':>8}")
print("-" * 70)
allres = {}
for name, cfg in CONFIGS.items():
    rows = run(cfg)
    e = evaluate(rows)
    allres[name] = (rows, e)
    f = lambda v: ("未报警" if v is None else f"{v}季度")
    print(f"{name:12} {f(e['顶2018Q3']):>11} {f(e['顶2022Q1']):>11} "
          f"{e['底2019Q4']:>11} {e['底2023Q3']:>11} {e['上行期误报']:>8}")

print("\n注：2018周期用于定参（样本内），2022周期为样本外验证。底温≥60视为有效底部指示。")
json.dump({k: v[0] for k, v in allres.items()},
          open(os.path.join(HERE, "compare_result.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)

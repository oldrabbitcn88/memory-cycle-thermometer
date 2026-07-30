#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""季度回测：用同一套规则重建历史分数，对比 v2 旧模型与 v3 新模型的报警时点。"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import scoring as sc

HERE = os.path.dirname(os.path.abspath(__file__))
data = json.load(open(os.path.join(HERE, "metrics_quarterly.json"), encoding="utf-8"))

rows, streak, phase = [], [0] * 5, "扩张期"
for item in data["quarters"]:
    scores = sc.score_all(item["m"])
    streak = sc.update_streak(streak, scores)
    phase = sc.next_phase(phase, scores)
    r = sc.compose(scores, sc.decay_factors(streak), phase)
    old = sc.legacy_total(scores)
    rows.append({"q": item["q"], "conf": item["conf"], "note": item["note"],
                 "s": scores, "old": old, "old_stage": sc.legacy_stage(old),
                 "new": r["total"], "new_stage": r["stage"],
                 "n50": r["n50"], "n75": r["n75"], "trig": r["triggers"], "phase": phase})

print(f"{'季度':8} {'①':>4}{'②':>4}{'③':>4}{'④':>4}{'⑤':>4} {'旧':>4} {'新':>4} {'灯':>5}  阶段(新)")
print("-" * 78)
for r in rows:
    lit = f"{r['n50']}/{r['n75']}"
    mark = " ◀" if r["trig"] else ""
    print(f"{r['q']:8} {r['s'][0]:4d}{r['s'][1]:4d}{r['s'][2]:4d}{r['s'][3]:4d}{r['s'][4]:4d} "
          f"{r['old']:4d} {r['new']:4d} {lit:>5}  {r['new_stage']}{mark}")

def first_warn(key, stage_key):
    for r in rows:
        if r[stage_key] == "拐点临近":
            return r["q"], r[key]
    return None, None

print("\n" + "=" * 78)
qo, vo = first_warn("old", "old_stage")
qn, vn = first_warn("new", "new_stage")
print(f"旧模型（纯线性加权）首次报警『拐点临近』：{qo}（{vo}分）")
print(f"新模型（触发覆盖+亮灯计数）首次报警：      {qn}（{vn}分）")
print(f"合约价实际见顶：2018Q3；崩盘确认：2018Q4（三星10/31砍capex、11月合约价两次下调）")

json.dump(rows, open(os.path.join(HERE, "backtest_result.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)

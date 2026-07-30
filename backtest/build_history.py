#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""构建统一口径历史：季度骨架(2018起) + 周度明细(实测)，分层存储避免口径混淆。"""
import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import scoring as sc
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

QS = json.load(open(os.path.join(HERE, "metrics_quarterly.json"), encoding="utf-8"))["quarters"]
WK = json.load(open(os.path.join(HERE, "weekly_now.json"), encoding="utf-8"))

quarterly, streak, phase, ps, pm = [], [0]*5, "扩张期", None, None
for it in QS:
    m = it["m"]
    for mm in m: mm.setdefault("production_cut", it.get("production_cut", False))
    s = sc.score_all(m); streak = sc.update_streak(streak, s)
    phase = sc.next_phase(phase, s)
    r = sc.compose(s, sc.decay_factors(streak), phase)
    b = sc.bottom_score(s, ps, m, pm)
    if it["q"] >= "2018":     # 用户要求：2018年起
        quarterly.append({"period": it["q"], "s": s, "top": r["total"], "bottom": b["total"],
                          "phase": phase, "n50": r["n50"], "n75": r["n75"],
                          "trig": bool(r["triggers"]), "conf": it["conf"], "note": it["note"],
                          "kind": "季度重建"})
    ps, pm = s, m

weekly = [{"period": w["date"], "s": w["s"], "top": w["top"], "bottom": w["bottom"],
           "phase": w["phase"], "n50": w["n50"], "n75": w["n75"], "trig": bool(w["trig"]),
           "conf": "high", "note": f"现货${w['spot']} ({w['wow']:+.2f}%)", "kind": "周度实测",
           "spot": w["spot"], "wow": w["wow"]} for w in WK["weekly"]]

out = {
  "schema": "v3",
  "caliber": "数值映射 + 触发覆盖 + 慢变量衰减 + 相位状态机",
  "_分层说明": "quarterly=季度规则重建(2018起,非实测); weekly=周度实测(真实现货价). 两者口径相同但数据性质不同，不可混为一条曲线解读。",
  "quarterly": quarterly,
  "weekly": weekly,
  "equity_anchor": WK["equity"],
  "streak_carryover": [0, 12, 4, 0, 4],
}
json.dump(out, open(os.path.join(ROOT, "data", "history_v3.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=1)
print(f"季度序列 {len(quarterly)} 期（{quarterly[0]['period']} → {quarterly[-1]['period']}）")
print(f"周度序列 {len(weekly)} 期（{weekly[0]['period']} → {weekly[-1]['period']}）")
print("\n历次触发警报:", [q["period"] for q in quarterly if q["trig"]])
print("识别为下行/筑底:", [q["period"] for q in quarterly if q["phase"] in ("下行期","筑底期")])

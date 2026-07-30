import json, os, sys, itertools
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import scoring as sc
HERE = os.path.dirname(os.path.abspath(__file__))
QS = json.load(open(os.path.join(HERE,"metrics_quarterly.json"), encoding="utf-8"))["quarters"]
rows, streak, phase = [], [0]*5, "扩张期"
for it in QS:
    m = it["m"]
    for mm in m: mm.setdefault("production_cut", it.get("production_cut", False))
    s = sc.score_all(m); streak = sc.update_streak(streak, s)
    phase = sc.next_phase(phase, s)
    rows.append({"q": it["q"], "s": s, "phase": phase})
IDX = {r["q"]: i for i, r in enumerate(rows)}
UP = {"2017Q1","2017Q2","2017Q3","2017Q4","2021Q1","2021Q2","2024Q1","2024Q2","2024Q3","2024Q4","2025Q1","2025Q2"}

def ev(t1, t2, t4):
    rule = lambda s: s[0] >= t1 and s[1] >= t2 and s[3] >= t4
    def lead(peak):
        pi = IDX[peak]; L = None
        for j in range(pi, -1, -1):
            ok = rule(rows[j]["s"]) and rows[j]["phase"] not in ("下行期","筑底期")
            if ok: L = pi - j
            elif L is not None: break
        return L
    f = sum(1 for r in rows if r["q"] in UP and rule(r["s"]) and r["phase"] not in ("下行期","筑底期"))
    return lead("2018Q3"), lead("2022Q1"), f

grid = list(itertools.product([30,35,38,40,45,50],[45,50,55,60,70,75],[20,30,35,40,50]))
good = [(a,b,c,*ev(a,b,c)) for a,b,c in grid]
ok2 = [g for g in good if g[3] is not None and g[4] is not None and g[3] >= 2 and g[4] >= 2 and g[5] == 0]
ok1 = [g for g in good if g[3] and g[4] and g[3] >= 1 and g[4] >= 1 and g[5] == 0]
print(f"网格总数 {len(grid)}")
print(f"两轮均提前≥1季且零误报： {len(ok1)} 组（{100*len(ok1)/len(grid):.0f}%）")
print(f"两轮均提前≥2季且零误报： {len(ok2)} 组（{100*len(ok2)/len(grid):.0f}%）")
print(f"\n满足『提前≥2季+零误报』的阈值范围：")
print(f"  ①现货 ∈ {sorted(set(g[0] for g in ok2))}")
print(f"  ②设备 ∈ {sorted(set(g[1] for g in ok2))}")
print(f"  ④需求 ∈ {sorted(set(g[2] for g in ok2))}")
best3 = [g for g in ok2 if g[3] >= 3 or g[4] >= 3]
print(f"\n能达到提前3季以上的组合: {len(best3)} 组" + (f" → {best3[:3]}" if best3 else "（无——2季是这套信号的物理上限）"))

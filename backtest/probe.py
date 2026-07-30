import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
import scoring as sc
HERE = os.path.dirname(os.path.abspath(__file__))
QS = json.load(open(os.path.join(HERE, "metrics_quarterly.json"), encoding="utf-8"))["quarters"]

rows, streak, phase, ps, pm = [], [0]*5, "扩张期", None, None
for it in QS:
    m = it["m"]
    for mm in m: mm.setdefault("production_cut", it.get("production_cut", False))
    s = sc.score_all(m); streak = sc.update_streak(streak, s)
    phase = sc.next_phase(phase, s)
    b = sc.bottom_score(s, ps, m, pm)
    rows.append({"q": it["q"], "s": s, "phase": phase, "bot": b["total"], "conf": it["conf"]})
    ps, pm = s, m

PEAK = {"2018Q3","2022Q1"}; BOT = {"2019Q4","2023Q3"}
UP = {"2017Q1","2017Q2","2017Q3","2017Q4","2021Q1","2021Q2","2024Q1","2024Q2","2024Q3","2024Q4","2025Q1","2025Q2"}

# 候选F：三要素齐备（价格动能转负 + 供给已在路上 + 需求出现裂痕）
def ruleF(s): return s[0] >= 38 and s[1] >= 55 and s[3] >= 35
# 候选G：仅价格动能转负 + 供给
def ruleG(s): return s[0] >= 38 and s[1] >= 55
# 候选B(现行)：四灯同亮 或 ①≥75 或 ①④双过50
def ruleB(s):
    n50 = sum(1 for x in s if x >= 50); n75 = sum(1 for x in s if x >= 75)
    return s[0] >= 75 or n75 >= 3 or n50 >= 4 or (s[0] >= 50 and s[3] >= 50)

print(f"{'季度':9}{'①':>4}{'②':>4}{'③':>4}{'④':>4}{'⑤':>4} {'相位':>6} {'底温':>5}  F  G  B   标注")
print("-"*82)
for r in rows:
    s = r["s"]; up = r["phase"] not in ("下行期","筑底期")
    f, g, b = ruleF(s) and up, ruleG(s) and up, ruleB(s) and up
    tag = "◆顶" if r["q"] in PEAK else ("◇底" if r["q"] in BOT else ("·上行" if r["q"] in UP else ""))
    print(f"{r['q']:9}{s[0]:4d}{s[1]:4d}{s[2]:4d}{s[3]:4d}{s[4]:4d} {r['phase']:>6} {r['bot']:5d}  "
          f"{'√' if f else '·'}  {'√' if g else '·'}  {'√' if b else '·'}   {tag}")

def lead(rule, peak):
    idx = {r["q"]: i for i, r in enumerate(rows)}; pi = idx[peak]; L = None
    for j in range(pi, -1, -1):
        ok = rule(rows[j]["s"]) and rows[j]["phase"] not in ("下行期","筑底期")
        if ok: L = pi - j
        elif L is not None: break
    return L
def fp(rule): return [r["q"] for r in rows if r["q"] in UP and rule(r["s"]) and r["phase"] not in ("下行期","筑底期")]

print("\n" + "="*82)
for nm, rule in (("F 三要素", ruleF), ("G 双要素", ruleG), ("B 现行v3", ruleB)):
    l18, l22 = lead(rule, "2018Q3"), lead(rule, "2022Q1")
    x = fp(rule)
    cur = rule(rows[-1]["s"])
    print(f"{nm}: 2018提前{l18}季 / 2022提前{l22}季 | 上行期误报{len(x)}次{x if x else ''} | 当前2026Q3是否触发: {'是' if cur else '否'}")

print("\n底部温度分布：")
hi = [(r["q"], r["bot"], r["q"] in BOT) for r in rows if r["bot"] >= 60]
for q, v, t in hi:
    print(f"  {q}: {v}分 {'◇真底部' if t else '（非标注底部）'}")

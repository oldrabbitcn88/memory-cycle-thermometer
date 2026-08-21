#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
存储周期温度计 · 打分引擎 v3（与采集层解耦，供 update.py 与 backtest.py 共用）

三项改造：
  改造3 数值映射：模型只负责提取原始指标，分数由本模块机械映射，消除自由裁量
  改造1 触发覆盖 + 亮灯计数：单信号极端值不再被加权平均稀释
  改造2 慢变量衰减：②⑤ 的存量风险不再向总温度贡献恒定底噪
"""

WEIGHTS = [0.25, 0.20, 0.20, 0.20, 0.15]
SLOW_SIGNALS = (1, 4)          # 索引：②设备订单、⑤叙事（0-based）
DECAY_GRACE = 2                # 亮灯前2期不衰减
DECAY_STEP = 0.12              # 此后每期衰减12%
DECAY_FLOOR = 0.40             # 衰减下限


# ---------- 改造3：五张数值映射表 ----------
def score_spot_contract(m: dict) -> int:
    """① premium_pct=现货相对合约溢价%(负=倒挂)，wow_pct=现货周环比%，weeks_down=连续下跌周数"""
    p, wow, wd = m["premium_pct"], m.get("wow_pct", 0.0), m.get("weeks_down", 0)
    if p < -5:    s = 95
    elif p < 0:   s = 85
    elif p < 3:   s = 60
    elif p < 10:  s = 40 if wow <= 0 else 32
    elif p < 20:  s = 25 if wow > 0 else 38
    else:         s = 10 if wow > 0 else 30
    # 动量升级：不论溢价绝对水平多高，动量转负本身就是信号。
    # （现实中溢价可达100%+，若只按溢价分档，触发器在高溢价regime下永远不可达）
    if wd >= 2:
        s = max(s, 38)
    if wd >= 4:
        s = max(s, 55)
    return min(100, s)


def score_capex(m: dict) -> int:
    """② yoy_pct=存储厂capex同比%，new_fabs=在建/新宣布fab数，new_entrant=新玩家扩产"""
    y = m["yoy_pct"]
    if y <= 0:    s = 15
    elif y < 15:  s = 35
    elif y < 30:  s = 55
    else:         s = 75
    s += 10 if m.get("new_fabs", 0) >= 2 else 0
    s += 5 if m.get("new_entrant") else 0
    return min(100, s)


def score_inventory(m: dict) -> int:
    """③ weeks=下游库存周数，lta=长约锁量盛行，sellout=售罄话术，cancel=砍单/毁约"""
    if m.get("cancel"):        return 85
    w = m["weeks"]
    if w > 10:   s = 80
    elif w >= 8: s = 65
    elif w >= 6: s = 55
    else:        s = 20
    if m.get("lta") and m.get("sellout"): s = max(s, 55)
    elif m.get("lta"):                    s = max(s, 40)
    return min(100, s)


def score_demand(m: dict) -> int:
    """④ n_cutting=明确削减/推迟的大客户数，peaked=增速见顶，doubt=回报率质疑出现"""
    n = m.get("n_cutting", 0)
    if n >= 2:  return 85
    if n == 1:  return 65
    if m.get("peaked"): return 50
    return 35 if m.get("doubt") else 20


def score_narrative(m: dict) -> int:
    """⑤ years_out=短缺预期覆盖年数，bears=公开提出异议的机构数，mega=龙头上市/巨额融资"""
    y = m["years_out"]
    if y > 3:    s = 80
    elif y > 2:  s = 60
    elif y > 1:  s = 40
    else:        s = 20
    if m.get("mega"): s += 10
    s -= 10 * min(2, m.get("bears", 0))
    return max(0, min(100, s))


SCORERS = [score_spot_contract, score_capex, score_inventory, score_demand, score_narrative]


def score_all(metrics: list) -> list:
    """metrics: 长度5的指标字典列表 → 长度5的水平分"""
    return [SCORERS[i](metrics[i]) for i in range(5)]


# ---------- 改造2：慢变量衰减 ----------
def decay_factors(lit_streak: list) -> list:
    """lit_streak[i] = 该信号已连续亮灯（≥50）的期数（含本期）。仅慢变量衰减。"""
    f = [1.0] * 5
    for i in SLOW_SIGNALS:
        over = max(0, lit_streak[i] - DECAY_GRACE)
        f[i] = max(DECAY_FLOOR, 1.0 - DECAY_STEP * over)
    return f


def update_streak(prev_streak: list, scores: list) -> list:
    return [(prev_streak[i] + 1 if scores[i] >= 50 else 0) for i in range(5)]


# ---------- 改造1：触发覆盖 + 亮灯计数 ----------
def compose(scores: list, factors: list, phase: str = "扩张期") -> dict:
    """合成总温度、亮灯计数与阶段。scores=水平分，factors=衰减系数。"""
    eff = [scores[i] * factors[i] for i in range(5)]
    total = int(round(sum(eff[i] * WEIGHTS[i] for i in range(5))))

    n50 = sum(1 for s in scores if s >= 50)
    n75 = sum(1 for s in scores if s >= 75)

    # 触发覆盖：单信号极端值不被加权平均稀释
    # 主触发器（回测定参）：现货动能转负 + 供给扩张已确立 + 需求出现裂痕。
    # 该组合在2018Q1与2021Q3各提前2个季度触发，零误报；180组阈值中54组同样成立
    # （平台而非刀尖）。①的阈值必须落在"动能转负"档(38)，等到"连跌4周"档(55)
    # 只剩1个季度提前量。
    triggers = []
    if scores[0] >= 38 and scores[1] >= 55 and scores[3] >= 35:
        triggers.append("三要素齐备：现货动能转负 + 供给扩张确立 + 需求现裂痕")
    if scores[0] >= 75:
        triggers.append("现货跌破合约（2018年的实际触发器）")
    if n75 >= 3:
        triggers.append("三盏以上红灯同亮")
    if scores[0] >= 50 and scores[3] >= 50:
        triggers.append("价格与需求引擎同步转向")

    # 相位优先：已过顶时，高分含义反转，不得再报"拐点临近"
    if phase in ("下行期", "筑底期"):
        desc = ("顶部已确认过去，价格与供给同步收缩中。" if phase == "下行期"
                else "跌幅收敛，供给纪律重建中，关注新一轮启动条件。")
        return {"total": total, "eff": [round(e, 1) for e in eff],
                "n50": n50, "n75": n75, "triggers": [], "phase": phase,
                "stage": phase, "stage_desc": desc}

    if triggers:
        stage, desc = "拐点临近", "触发覆盖规则已激活——不以加权总分为准。"
    elif n50 >= 4:
        stage, desc = "拐点临近", "四盏以上黄灯同亮，组合确认。"
    elif total < 30:
        stage, desc = "景气上行期", "信号面干净，主要风险是踏空而非站岗。"
    elif total < 50:
        stage, desc = "过热前期", "上行动能仍在，供给端/叙事端开始积累矛盾。"
    elif total < 60:
        stage, desc = "过热中期 → 顶部预警", "供需矛盾持续积累，历史上距周期转折约6–12个月。"
    else:
        # 阈值按两轮周期的实际峰值标定：2018 轮最高 61、2022 轮最高 62。
        # 原阈值 70 在 35 期回测中从未触及，那条分支是死代码。
        stage, desc = "拐点临近", "温度已进入历史顶部区间（两轮周期峰值 61–62）。"

    return {"total": total, "eff": [round(e, 1) for e in eff],
            "n50": n50, "n75": n75, "triggers": triggers, "phase": phase,
            "stage": stage, "stage_desc": desc}


def legacy_total(scores: list) -> int:
    """v2 旧模型：纯线性加权，用于新旧对比"""
    return int(round(sum(scores[i] * WEIGHTS[i] for i in range(5))))


def legacy_stage(total: int) -> str:
    if total < 30: return "景气上行期"
    if total < 50: return "过热前期"
    if total < 70: return "过热中期 → 顶部预警"
    return "拐点临近"

# ---------- 改造4：周期相位状态机（回测发现的缺陷修补） ----------
# 问题：信号①"现货跌破合约"在整个下行期都维持85-95分，使温度计在周期底部
# 仍报"拐点临近"（回测中2023Q2周期底部误报）。温度计必须区分"上行接近顶部"
# 与"已过顶下行"——同样的高分，含义完全相反。
PHASES = ("扩张期", "顶部预警", "下行期", "筑底期")


def next_phase(prev_phase: str, scores: list) -> str:
    spot, capex = scores[0], scores[1]
    if prev_phase in ("下行期", "筑底期"):
        # 复位条件：现货重回合约价上方 且 供给端重新扩张
        if spot < 50 and capex >= 35:
            return "扩张期"
        # 下行→筑底：跌幅收敛
        if prev_phase == "下行期" and spot < 70:
            return "筑底期"
        if prev_phase == "筑底期" and spot >= 85:
            return "下行期"
        return prev_phase
    # 顶部已过的确认：价格倒挂 + 供给端投降（capex转负）
    if spot >= 75 and capex <= 20:
        return "下行期"
    if spot >= 50 or scores[3] >= 50:
        return "顶部预警"
    return "扩张期"


# ---------- 底部温度：周期底部的积极指示 ----------
# 顶部温度用"水平值"即可，底部温度必须用"变化率"——因为底部的特征不是
# "库存高"（那是下行期），而是"库存正在去化、价格正在企稳、供给已经投降"。
def bottom_score(scores: list, prev_scores: list, m: list, prev_m: list) -> dict:
    if prev_scores is None:
        return {"total": 0, "parts": [0, 0, 0, 0]}

    # 供给投降：capex深度负 + 明确减产公告
    supply = 100 - scores[1]
    if m[1].get("production_cut") or prev_m[1].get("production_cut"):
        supply = min(100, supply + 15)

    # 库存去化：本期库存周数相对上期的下降幅度
    w0, w1 = prev_m[2].get("weeks", 8), m[2].get("weeks", 8)
    destock = max(0.0, (w0 - w1) / max(w0, 1e-6)) * 320
    destock = min(100.0, destock)

    # 价格企稳：溢价从深度负值回升（回升幅度，且仍在低位才算数）
    p0, p1 = prev_m[0]["premium_pct"], m[0]["premium_pct"]
    if p0 < 5:
        stabilize = min(100.0, max(0.0, (p1 - p0)) * 12)
        if p1 > 0 and p0 <= 0:
            stabilize = min(100.0, stabilize + 30)   # 由负转正：关键确认
    else:
        stabilize = 0.0

    # 悲观一致性（逆向）：叙事分越低越好
    pessimism = 100 - scores[4]

    parts = [supply, destock, stabilize, pessimism]
    total = int(round(0.30 * supply + 0.25 * destock + 0.25 * stabilize + 0.20 * pessimism))
    return {"total": total, "parts": [round(x) for x in parts]}


# ---------- 市场定价锚（独立于合成分，不参与已定标的打分）----------
# 回测数据集无法覆盖股价序列（Roundhill DRAM ETF 成立较晚），故不纳入合成分，
# 但2018年美光股价5月见顶、领先合约价见顶(Q3)约4个月；2022年同样领先。
# 该信号数据免费、日频，且当前正在极端背离，单列告警。
def equity_anchor(etf_price: float, etf_high: float, spot_at_record: bool) -> dict:
    dd = (etf_price / etf_high - 1.0) * 100.0 if etf_high else 0.0
    alert = (dd <= -25.0 and spot_at_record)
    return {
        "drawdown_pct": round(dd, 1),
        "alert": alert,
        "note": ("资本市场已深度回撤而现货仍创新高——前瞻定价先于现货转向，"
                 "2018/2022两轮均出现此形态" if alert else "资本市场定价与现货未见显著背离"),
    }


# ---------- 解释层：把打分规则翻译成可读说明 ----------
# 说明文本不手写。手写的 prose 迟早和代码漂移，而本项目的全部卖点就是
# "打分规则集中在 scoring.py，不可能出现两套口径"。
# 这里把分档表写成数据，再用 verify_explain() 在输入网格上逐点比对
# 表与真实 scorer 的输出——表一旦和 scorer 不一致，probe.py 立刻报错。

SPOT_PREMIUM_ASSUMED = 120.0   # 见 update.py：合约价无数据源，这是写死的假设值


def _base(rules, hit):
    """分档表里命中档的基础分（尚未叠加修饰项）。"""
    for r in rules:
        if r["cond"] == hit:
            return r["score"]
    return None


def _fmt(x):
    return str(int(x)) if isinstance(x, float) and x == int(x) else str(x)


def explain_spot(m):
    """① 现货价动能。premium_pct 是假设常量，实际起作用的只有 wow 与 weeks_down。"""
    wow, wd = m.get("wow_pct", 0.0), m.get("weeks_down", 0)
    rules = [
        {"cond": "现货环比上涨", "score": 10},
        {"cond": "现货环比下跌或持平", "score": 30},
        {"cond": "连续下跌 ≥2 期", "score": "至少 38"},
        {"cond": "连续下跌 ≥4 期", "score": "至少 55"},
    ]
    if wd >= 4:   hit = "连续下跌 ≥4 期"
    elif wd >= 2: hit = "连续下跌 ≥2 期"
    elif wow > 0: hit = "现货环比上涨"
    else:         hit = "现货环比下跌或持平"
    nxt = ("再跌 %d 期跳到「至少 38」——那正是主触发器对本信号的门槛" % (2 - wd)
           if wd < 2 else
           "再跌 %d 期跳到「至少 55」" % (4 - wd) if wd < 4 else "已在最高档")
    return {
        "range": "DDR4 1Gx8 3200MT/s 主流现货价，来源 TrendForce / DRAMeXchange 官方快照"
                 "（经 Capital & Compute 聚合的免费公开部分）。数据源按不定期发布，非严格周频。",
        "rules": rules, "hit": hit, "next": nxt,
        "base": _base(rules, hit), "final": score_spot_contract(m),
        "role": "主触发器三要素之一，门槛 ≥38（即「动能转负」档）",
        "caveat": "本信号原名「现货价 vs 合约价」，但合约价无公开数据源，"
                  "溢价 %s%% 是写死的假设值、不参与实际判档，故更名为「现货价动能」。"
                  % _fmt(SPOT_PREMIUM_ASSUMED),
    }


def explain_capex(m):
    """② 设备商存储订单"""
    y = m["yoy_pct"]
    rules = [{"cond": "capex 同比 ≤0%", "score": 15}, {"cond": "0–15%", "score": 35},
             {"cond": "15–30%", "score": 55}, {"cond": "≥30%", "score": 75}]
    hit = "≥30%" if y >= 30 else "15–30%" if y >= 15 else "0–15%" if y > 0 else "capex 同比 ≤0%"
    add = []
    if m.get("new_fabs", 0) >= 2: add.append("在建/新宣布 fab ≥2 座 +10")
    if m.get("new_entrant"):      add.append("有新玩家扩产 +5")
    return {
        "range": "三大存储原厂（三星/海力士/美光）资本开支同比，季度更新，"
                 "取自各家财报与设备商（ASML/AMAT/Lam）订单指引。本期数值 asof %s。"
                 % m.get("asof", "—"),
        "rules": rules, "hit": hit, "adds": add,
        "base": _base(rules, hit), "final": score_capex(m),
        "next": "capex 同比跌破 30% 降到 55 档；跌破 15% 降到 35 档",
        "role": "主触发器三要素之一，门槛 ≥55（即「供给扩张已确立」）",
        "caveat": "慢变量：连续亮灯超过 2 期后按每期 12% 衰减（下限 40%），"
                  "避免存量风险向总温度贡献恒定底噪。",
    }


def explain_inventory(m):
    """③ 下游库存与囤货"""
    w = m["weeks"]
    rules = [{"cond": "已出现砍单/毁约", "score": 85}, {"cond": "库存 >10 周", "score": 80},
             {"cond": "库存 8–10 周", "score": 65}, {"cond": "库存 6–8 周", "score": 55},
             {"cond": "库存 <6 周", "score": 20}]
    if m.get("cancel"): hit = "已出现砍单/毁约"
    elif w > 10:        hit = "库存 >10 周"
    elif w >= 8:        hit = "库存 8–10 周"
    elif w >= 6:        hit = "库存 6–8 周"
    else:               hit = "库存 <6 周"
    add = []
    if m.get("lta") and m.get("sellout"): add.append("长约锁量 + 售罄话术 → 下限抬到 55")
    elif m.get("lta"):                    add.append("长约锁量 → 下限抬到 40")
    cur = score_inventory(m)
    nxt = "已在最高档"
    for need, band, val in ((6, "6–8 周", 55), (8, "8–10 周", 65), (10.01, ">10 周", 80)):
        if val > cur and w < need:
            nxt = "库存再涨 %s 周进入 %s档（%d 分）" % (_fmt(round(need - w, 1)), band, val)
            break
    return {
        "range": "下游模组厂与终端客户的存货周数，季度更新，来自厂商财报存货天数与渠道调研。"
                 "本期数值 asof %s。" % m.get("asof", "—"),
        "rules": rules, "hit": hit, "adds": add, "next": nxt,
        "base": _base(rules, hit), "final": cur,
        "caveat": "「砍单」是一票否决式的最高档：它直接给 85，不再看库存周数——"
                  "历史上砍单出现时，周期顶部基本已经确认。",
    }


def explain_demand(m):
    """④ 需求引擎(AI capex)"""
    rules = [{"cond": "≥2 家大客户明确削减/推迟", "score": 85},
             {"cond": "1 家削减", "score": 65},
             {"cond": "增速见顶（无人削减）", "score": 50},
             {"cond": "出现回报率质疑", "score": 35},
             {"cond": "以上皆无", "score": 20}]
    n = m.get("n_cutting", 0)
    hit = ("≥2 家大客户明确削减/推迟" if n >= 2 else "1 家削减" if n == 1 else
           "增速见顶（无人削减）" if m.get("peaked") else
           "出现回报率质疑" if m.get("doubt") else "以上皆无")
    return {
        "range": "统计范围为超大规模云厂商（微软/谷歌/亚马逊/Meta/甲骨文等）的 AI 资本开支指引，"
                 "季度更新，以公开财报电话会中的明确表述为准。本期数值 asof %s。" % m.get("asof", "—"),
        "rules": rules, "hit": hit,
        "base": _base(rules, hit), "final": score_demand(m),
        "next": "任一家明确削减即跳到 65；两家跳到 85",
        "role": "主触发器三要素之一，门槛 ≥35（即「需求已现裂痕」）",
    }


def explain_narrative(m):
    """⑤ 行业预期一致性"""
    rules = [{"cond": "短缺预期覆盖 >3 年", "score": 80}, {"cond": ">2 年", "score": 60},
             {"cond": ">1 年", "score": 40}, {"cond": "≤1 年", "score": 20}]
    y = m["years_out"]
    hit = "短缺预期覆盖 >3 年" if y > 3 else ">2 年" if y > 2 else ">1 年" if y > 1 else "≤1 年"
    add = []
    if m.get("mega"): add.append("龙头上市/巨额融资 +10")
    if m.get("bears"): add.append("每有 1 方公开提出异议 −10（最多 −20），本期 %d 方" % m["bears"])
    return {
        "range": "统计范围为主流行业研究与产业媒体对存储短缺持续时间的一致预期，"
                 "季度更新。本期数值 asof %s。" % m.get("asof", "—"),
        "rules": rules, "hit": hit, "adds": add,
        "base": _base(rules, hit), "final": score_narrative(m),
        "caveat": "反向指标：一致性越强、预测越远，越接近周期顶部。"
                  "与②同为慢变量，连续亮灯超过 2 期后按每期 12% 衰减。",
    }


EXPLAINERS = [explain_spot, explain_capex, explain_inventory, explain_demand, explain_narrative]


def explain_all(metrics):
    return [EXPLAINERS[i](metrics[i]) for i in range(5)]


def verify_explain():
    """在输入网格上逐点比对「规则表」与真实 scorer。

    校验方式：把各信号的修饰项（fab 数、长约、砍单、看空方数等）全部置于默认值，
    此时 explain 声明的命中档位分数必须等于 scorer 的实际输出。
    修饰项本身另行断言其方向与幅度。返回问题列表，空列表即通过。
    """
    bad = []

    def chk(tag, expect, actual, ctx):
        if expect != actual:
            bad.append("%s: 表说 %s，scorer 给 %s（输入 %s）" % (tag, expect, actual, ctx))

    def base_of(ex):
        for r in ex["rules"]:
            if r["cond"] == ex["hit"]:
                return r["score"]
        bad.append("命中档 %r 不在规则表内" % ex["hit"])
        return None

    # ① 现货动能：wd=0 时只由 wow 决定
    for wow in (-8.0, -0.5, 0.0, 0.01, 3.28, 12.0):
        m = {"premium_pct": SPOT_PREMIUM_ASSUMED, "wow_pct": wow, "weeks_down": 0}
        chk("①", base_of(explain_spot(m)), score_spot_contract(m), m)
    for wd, floor in ((2, 38), (3, 38), (4, 55), (7, 55)):
        m = {"premium_pct": SPOT_PREMIUM_ASSUMED, "wow_pct": -1.0, "weeks_down": wd}
        s = score_spot_contract(m)
        if s < floor:
            bad.append("①: 连跌%d期应 ≥%d，实得 %d" % (wd, floor, s))

    # ② capex：无 fab 加成、无新玩家
    for y in (-10, 0, 1, 14.9, 15, 29.9, 30, 60):
        m = {"yoy_pct": y, "new_fabs": 0, "new_entrant": False}
        chk("②", base_of(explain_capex(m)), score_capex(m), m)
    chk("②fab", score_capex({"yoy_pct": 40, "new_fabs": 0, "new_entrant": False}) + 10,
        score_capex({"yoy_pct": 40, "new_fabs": 2, "new_entrant": False}), "new_fabs=2")

    # ③ 库存：无砍单、无长约
    for w in (0, 5.9, 6, 7.9, 8, 10, 10.1, 14):
        m = {"weeks": w, "lta": False, "sellout": False, "cancel": False}
        chk("③", base_of(explain_inventory(m)), score_inventory(m), m)
    m = {"weeks": 3.5, "lta": True, "sellout": True, "cancel": False}
    chk("③长约", 55, score_inventory(m), m)

    # ④ 需求：规则表即全部逻辑
    for n, pk, db in ((0, False, False), (0, False, True), (0, True, False), (1, False, False), (3, True, True)):
        m = {"n_cutting": n, "peaked": pk, "doubt": db}
        chk("④", base_of(explain_demand(m)), score_demand(m), m)

    # ⑤ 叙事：无 mega、无看空
    for y in (0.5, 1, 1.5, 2, 2.5, 3, 4.0):
        m = {"years_out": y, "bears": 0, "mega": False}
        chk("⑤", base_of(explain_narrative(m)), score_narrative(m), m)
    chk("⑤看空", score_narrative({"years_out": 4.0, "bears": 0, "mega": False}) - 20,
        score_narrative({"years_out": 4.0, "bears": 3, "mega": False}), "bears=3（封顶 −20）")

    return bad


# ---------- 触底信号（原「底部温度」）的解释 ----------
# 改名原因：两个读数都叫「温度」，读者必然以为是同一根尺子的两端，
# 反复引发"41 和 7 哪个才是真温度"的误读。JSON 字段名仍为 bottom，不动，
# 以免线上旧版本代码包读不到——只改展示名。
BOTTOM_PARTS = [
    ("供给投降", 0.30, "capex 转负、出现明确减产公告。原厂停止扩产是周期见底的前置条件。"),
    ("库存去化", 0.25, "下游库存周数相对上期的下降幅度。注意是「正在降」而非「已经低」。"),
    ("价格企稳", 0.25, "现货溢价从深度负值回升；由负转正额外加分，那是关键确认。"),
    ("预期转向", 0.20, "行业叙事由乐观转向谨慎的程度（信号⑤的反面）。产业普遍转向保守时，往往已接近周期底部。"),
]


def explain_bottom(parts, total):
    """parts = bottom_score() 返回的四个分项，顺序同 BOTTOM_PARTS。"""
    rows = [{"name": n, "weight": int(w * 100), "score": (parts[i] if parts and i < len(parts) else 0),
             "desc": d} for i, (n, w, d) in enumerate(BOTTOM_PARTS)]
    zero = [r["name"] for r in rows if r["score"] == 0]
    return {
        "what": "触底信号回答的是「反转条件凑齐了没有」，和行业温度问的「危不危险」"
                "是两个独立问题，不是同一根尺子的两端。",
        "why": "周期底部的特征不是「库存高」——那是下行期的特征——而是「库存正在去化、"
               "价格正在企稳、供给已经投降」。水平值看不出这个，只有变化率能，"
               "所以它必须用另一套算法，也就必然是另一个数。",
        "parts": rows,
        "total": total,
        "gate": "≥60 才算反转条件集齐。低于 60 只说明产业尚未出现触底特征，与景气好坏无关。",
        "example": "2018Q1 与 2019Q4 的行业温度都是 36°，但触底信号一个 18、一个 99——"
                   "前者是上行刚起步，后者是周期最底部。温度分不开的，这个数分得开。",
        "zero_note": ("本期 %s 为 0，是总分偏低的主因。" % "、".join(zero)) if zero else "",
    }

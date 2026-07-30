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
    """⑤ years_out=短缺预测覆盖年数，bears=公开看空方数量，mega=龙头上市/巨额融资"""
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
    elif total < 70:
        stage, desc = "过热中期 → 顶部预警", "距拐点历史上约6–12个月，应制定退出触发条件。"
    else:
        stage, desc = "拐点临近", "加权总分已进入高位区间。"

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
        "note": ("股价已深度回撤而现货仍创新高——前瞻定价先于现货转向，"
                 "2018/2022两轮均出现此形态" if alert else "股价与现货未见显著背离"),
    }

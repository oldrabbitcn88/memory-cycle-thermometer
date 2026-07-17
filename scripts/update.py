#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
存储周期温度计 · 每周更新脚本
流程：调 Claude API（开 web search）按固定规则给 5 个信号打分
     → 本地重算加权总分（不信任模型算术）→ 校验来源链接
     → 追加真实历史 → 生成 data/data.json → 上传微信云开发存储。
密钥全部来自环境变量（GitHub Secrets），本脚本及产出物中不含任何密钥。
"""
import json
import os
import re
import sys
import datetime

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HISTORY_PATH = os.path.join(ROOT, "data", "history.json")
DATA_PATH = os.path.join(ROOT, "data", "data.json")

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
WX_APPID = os.environ["WX_APPID"]
WX_SECRET = os.environ["WX_SECRET"]
TCB_ENV = os.environ["TCB_ENV"]
MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5")
CLOUD_PATH = os.environ.get("CLOUD_PATH", "data.json")  # 云存储中的文件路径

WEIGHTS = [0.25, 0.20, 0.20, 0.20, 0.15]
SIGNALS_META = [
    {"id": 1, "name": "现货价 vs 合约价倒挂", "lead": "领先约1–2个季度 · 最直接的拐点触发器"},
    {"id": 2, "name": "设备商存储订单增速", "lead": "领先12–18个月 · 供给释放的先行指标"},
    {"id": 3, "name": "下游库存与囤货行为", "lead": "领先2–3个季度 · 表观需求虚增的检验器"},
    {"id": 4, "name": "最大需求引擎的边际变化（AI capex）", "lead": "核心变量 · 上轮是手机+挖矿，本轮是云厂商"},
    {"id": 5, "name": "卖方一致性与管理层话术", "lead": "反向指标 · 预测年份后移=警觉信号"},
]

RULEBOOK = """① 现货vs合约（权重25%）：0-25 现货显著高于合约且持续上涨；25-50 现货仍高但涨幅收窄/成交清淡/买方抵制报价；50-75 价差收敛至±3%以内或现货连跌4周；75-100 现货跌破合约（倒挂确认）
② 设备订单（权重20%）：0-25 存储厂capex同比下降或持平；25-50 温和回升<+15%；50-75 同比+15~30%或有新建fab宣布；75-100 同比>+30%且多座新fab并行+新玩家（CXMT等）同步扩产
③ 下游库存（权重20%）：0-25 下游库存<4周且无长约锁量；25-50 库存正常但长约/预订比例上升；50-75 长约锁量盛行+"全年售罄"话术+重复下单迹象；75-100 渠道库存>10周或大客户砍单/毁约长约
④ 需求引擎（权重20%）：0-25 云厂商capex指引持续上调无一家松口；25-50 指引仍增长但增速见顶/出现回报率质疑声；50-75 有云厂商下调指引或推迟数据中心项目；75-100 ≥2家大厂明确削减capex
⑤ 叙事一致性（权重15%）：0-25 卖方分歧大、管理层谨慎提供给纪律；25-50 一致看多但预测期限稳定；50-75 短缺预测年份开始后移、"这次不一样"叙事流行；75-100 预测后移至3年以上+龙头上市/巨额融资+几乎无人看空"""


def beijing_today() -> str:
    tz = datetime.timezone(datetime.timedelta(hours=8))
    return datetime.datetime.now(tz).strftime("%Y-%m-%d")


def stage_of(total: int):
    if total < 30:
        return "景气上行期", "价格上行初中段，信号面干净。主要风险是踏空而非站岗。"
    if total < 50:
        return "过热前期", "上行动能仍在，但供给端/叙事端开始积累矛盾，需每周核对领先信号。"
    if total < 70:
        return "过热中期 → 顶部预警", "多个领先信号亮黄/红灯。历史上此阶段距拐点约6–12个月，应制定退出触发条件。"
    return "拐点临近", "领先信号组合确认。2018年教训：此时叙事最强、股价未必已跌，正是最难卖出的时刻。"


def build_prompt(history: list) -> str:
    last = history[-1] if history else None
    last_txt = (
        f"上期读数（{last['date']}）：五信号分数 {last['s']}，总温度 {last['total']}。摘要：{last.get('note','无')}"
        if last else "无上期读数（首次运行）。"
    )
    return f"""你是存储芯片（DRAM/NAND）周期监测助手。今天是 {beijing_today()}。请完成：

一、用网络搜索逐一核实以下 5 个维度的最近两周动态（优先 TrendForce、DRAMeXchange、Tom's Hardware、公司财报与官方指引）：
1. DRAM/NAND 现货价 vs 合约价：最新周度现货走势、成交活跃度、现货与合约价差方向
2. 存储设备订单/capex：三星、SK海力士、美光、CXMT 的 capex 与新 fab 进展、WFE 装机节奏
3. 下游库存与囤货：OEM/渠道库存周数、长约锁量、售罄/砍单/递延交货迹象
4. AI 需求引擎：微软/谷歌/亚马逊/Meta 最新 capex 指引及措辞变化、有无下调或推迟
5. 叙事与一致性：管理层短缺预测年份是否又后移、卖方有无新增看空声音

二、严格按以下固定规则为每个信号打 0-100 分（分数越高越接近周期顶部），不得偏离规则自由发挥：
{RULEBOOK}

三、{last_txt}

四、只输出一个 JSON 对象（不要输出任何其他文字、不要用代码块包裹），结构如下：
{{
  "signals": [
    {{"score": <0-100整数>, "reading": "<80-150字中文本期读数，含关键数字>", "sources": [{{"title": "<来源名>", "url": "<真实URL>"}}]}},
    ... 共5项，严格按上面1-5的顺序 ...
  ],
  "comment": "<150-250字本期点评：与上期相比哪些信号升温/降温、下周最该盯什么>",
  "note": "<一句话本期摘要，30字以内>"
}}

硬性要求：每个信号至少 1 条 sources 且 url 必须来自你本次搜索到的真实网页，严禁编造链接；打分只依据搜到的事实，找不到新信息的维度沿用上期分数并在 reading 中注明"本期无增量信息"。"""


def call_claude(history: list) -> dict:
    body = {
        "model": MODEL,
        "max_tokens": 8000,
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": 12}],
        "messages": [{"role": "user", "content": build_prompt(history)}],
    }
    r = requests.post(
        "https://gw.claudeapi.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=body,
        timeout=900,
    )
    r.raise_for_status()
    text = "".join(
        b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text"
    )
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        sys.exit(f"[错误] 模型未返回 JSON，原文前 2000 字：\n{text[:2000]}")
    return json.loads(m.group(0))


def validate(result: dict) -> list:
    sigs = result.get("signals")
    if not isinstance(sigs, list) or len(sigs) != 5:
        sys.exit("[错误] signals 必须是长度为 5 的数组")
    for i, s in enumerate(sigs):
        sc = s.get("score")
        if not isinstance(sc, (int, float)) or not (0 <= sc <= 100):
            sys.exit(f"[错误] 信号{i+1} 分数非法：{sc}")
        s["score"] = int(round(sc))
        srcs = [x for x in s.get("sources", []) if str(x.get("url", "")).startswith("http")]
        if not srcs:
            sys.exit(f"[错误] 信号{i+1} 缺少真实来源链接——宁可失败也不发布无来源数据")
        s["sources"] = srcs[:4]
        if not s.get("reading"):
            sys.exit(f"[错误] 信号{i+1} 缺少 reading")
    return sigs


def wx_upload(content: bytes):
    """上传 data.json 到微信云开发存储（同路径覆盖，fileID 恒定不变）。"""
    tok = requests.get(
        "https://api.weixin.qq.com/cgi-bin/token",
        params={"grant_type": "client_credential", "appid": WX_APPID, "secret": WX_SECRET},
        timeout=30,
    ).json()
    if "access_token" not in tok:
        sys.exit(f"[错误] 获取 access_token 失败：{tok}（检查 WX_APPID/WX_SECRET，"
                 f"并确认小程序后台未开启 IP 白名单，或白名单含 Actions 出口 IP）")
    up = requests.post(
        f"https://api.weixin.qq.com/tcb/uploadfile?access_token={tok['access_token']}",
        json={"env": TCB_ENV, "path": CLOUD_PATH},
        timeout=30,
    ).json()
    if up.get("errcode", 0) != 0:
        sys.exit(f"[错误] 获取上传链接失败：{up}（检查 TCB_ENV 环境 ID）")
    resp = requests.post(
        up["url"],
        files={
            "key": (None, CLOUD_PATH),
            "Signature": (None, up["authorization"]),
            "x-cos-security-token": (None, up["token"]),
            "x-cos-meta-fileid": (None, up["cos_file_id"]),
            "file": (CLOUD_PATH, content, "application/json"),
        },
        timeout=60,
    )
    if resp.status_code not in (200, 204):
        sys.exit(f"[错误] COS 上传失败：HTTP {resp.status_code} {resp.text[:500]}")
    print("=" * 60)
    print("上传成功。小程序端 config.js 需要的 fileID（恒定不变，只需配置一次）：")
    print(f"  {up['file_id']}")
    print("=" * 60)


def main():
    with open(HISTORY_PATH, encoding="utf-8") as f:
        history = json.load(f)

    result = call_claude(history)
    sigs = validate(result)

    # 总分由脚本本地重算，不采用模型给出的任何合计值
    scores = [s["score"] for s in sigs]
    total = int(round(sum(sc * w for sc, w in zip(scores, WEIGHTS))))
    stage, stage_desc = stage_of(total)
    today = beijing_today()

    # 真实累积历史：同日期覆盖（重跑场景），否则追加；绝不由模型生成历史
    entry = {"date": today, "s": scores, "total": total, "note": result.get("note", "")}
    history = [h for h in history if h["date"] != today] + [entry]
    history.sort(key=lambda h: h["date"])

    data = {
        "updated": today,
        "total": total,
        "stage": stage,
        "stage_desc": stage_desc,
        "weights": WEIGHTS,
        "signals": [
            {**meta, "weight": WEIGHTS[i], "score": sigs[i]["score"],
         "reading": sigs[i]["reading"], "sources": sigs[i]["sources"]}
            for i, meta in enumerate(SIGNALS_META)
        ],
        "comment": result.get("comment", ""),
        "history": history,
        "disclaimer": "本页面为个人研究用途的公开信息聚合，由程序按固定规则自动生成，可能存在错误或延迟，不构成任何投资建议。",
    }

    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    with open(DATA_PATH, "wb") as f:
        f.write(payload)

    print(f"本期读数 {today}：signals={scores} total={total} 阶段={stage}")
    wx_upload(payload)


if __name__ == "__main__":
    main()

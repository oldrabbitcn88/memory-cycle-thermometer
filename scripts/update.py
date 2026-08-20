#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
存储周期温度计 · 每周更新（v3.1）

架构变更（因中转网关的 web_search 实现不可用而重构）：
  第一层 确定性抓取：现货价、股价锚 —— 由 fetcher.py 正则解析，不经过任何 LLM。
                     这两项是唯一按周变动的指标，也是主触发器的判据，必须可靠。
  第二层 人工维护：季度类指标读 data/quarterly_inputs.json。它们本就按季更新，
                   自动抓取的误判风险远大于收益。
  第三层 可选点评：LLM 仅生成一句话摘要，失败不影响出分（且不依赖搜索能力）。
分数全部由 scoring.py 机械映射，任何一层都不参与打分。
"""
import json, os, sys, datetime
import scoring as sc
import fetcher

# 上传后端二选一（详见 README「数据托管」）：
#   ① 云开发 Storage：设 TCB_ENV，由 TCB API 反查桶名。环境停服/欠费即整站失联。
#   ② 普通 COS 桶  ：设 COS_BUCKET（可选 COS_REGION），直连上传，与云开发计费解耦。
# 两者共用同一对密钥；COS_BUCKET 一经设置即优先，此时 TCB_ENV 可留空。
TCB_ID  = os.environ.get("TCB_SECRET_ID", "").strip()
TCB_KEY = os.environ.get("TCB_SECRET_KEY", "").strip()
TCB_ENV = os.environ.get("TCB_ENV", "").strip()
COS_BUCKET = os.environ.get("COS_BUCKET", "").strip()
COS_REGION = os.environ.get("COS_REGION", "ap-shanghai").strip()
CLOUD_PATH = os.environ.get("CLOUD_PATH", "data.json")
TCB_REGION = os.environ.get("TCB_API_REGION", "ap-shanghai")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(ROOT, "data", "history_v3.json")
QIN  = os.path.join(ROOT, "data", "quarterly_inputs.json")
OUT  = os.path.join(ROOT, "data", "data.json")

NAMES = ["现货价 vs 合约价", "设备商存储订单", "下游库存与囤货", "需求引擎(AI capex)", "卖方一致性与话术"]
LEADS = ["领先1–2季度 · 主触发器", "领先12–18个月 · 背景条件", "领先2–3季度",
         "核心变量 · 门槛条件", "反向指标 · 背景条件"]


def bj_today():
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime("%Y-%m-%d")


def optional_note(scores, spot, eq):
    """可选：LLM 一句话摘要。任何失败都静默降级为规则生成的摘要。"""
    fallback = (f"现货${spot['latest']}（{'创新高' if spot['at_record'] else '未创新高'}），"
                f"连跌{spot['weeks_down']}周；股价距高点{eq['drawdown_pct']}%" if eq else
                f"现货${spot['latest']}，连跌{spot['weeks_down']}周")
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key or os.environ.get("DISABLE_LLM_NOTE") == "1":
        return fallback
    try:
        import anthropic
        cli = anthropic.Anthropic(api_key=key,
                                  base_url=os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
                                  timeout=120.0)
        msg = cli.messages.create(
            model=os.environ.get("CLAUDE_MODEL", "claude-sonnet-5"), max_tokens=300,
            messages=[{"role": "user", "content":
                f"存储周期监测本期数据：五信号分数{scores}（越高越接近周期顶部），"
                f"现货${spot['latest']}较上期${spot['prev']}，连续下跌{spot['weeks_down']}周，"
                f"{'创历史新高' if spot['at_record'] else '未创新高'}；"
                f"存储股ETF距高点{eq['drawdown_pct'] if eq else 'NA'}%。"
                f"用一句话（40字内）陈述本期最值得注意的事实，只陈述不判断，不要任何前后缀。"}])
        t = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        return t[:80] if t else fallback
    except Exception as e:
        print(f"[提示] LLM 点评不可用（不影响出分）：{e}")
        return fallback


def main(dry_run=False, no_upload=False):
    hist = json.load(open(HIST, encoding="utf-8"))
    qin = json.load(open(QIN, encoding="utf-8"))

    # --- 第一层：确定性抓取 ---
    spot = fetcher.fetch_spot()
    eq_raw = fetcher.fetch_equity()
    print(f"[抓取] 现货 {spot['latest_date']} ${spot['latest']}（上期 {spot['prev_date']} ${spot['prev']}）"
          f" 连跌{spot['weeks_down']}周 序列{spot['series_len']}条")
    print(f"[抓取] 股价锚 {eq_raw}")

    wow = (spot["latest"] / spot["prev"] - 1) * 100 if spot.get("prev") else 0.0

    # --- 第二层：季度指标（人工维护，带新鲜度标记）---
    clean = lambda d: {k: v for k, v in d.items() if not k.startswith("_")}
    metrics = [
        {"premium_pct": 120.0, "wow_pct": round(wow, 2), "weeks_down": spot["weeks_down"]},
        clean(qin["capex"]), clean(qin["inventory"]), clean(qin["demand"]), clean(qin["narrative"]),
    ]
    prev_q = hist.get("last_quarterly_asof", {})
    fresh = {NAMES[i+1]: (qin[k].get("asof") != prev_q.get(k)) for i, k in
             enumerate(["capex", "inventory", "demand", "narrative"])}

    # --- 打分（机械映射）---
    scores = sc.score_all(metrics)
    streak = sc.update_streak(hist.get("streak_carryover", [0]*5), scores)
    phase = sc.next_phase(hist.get("last_phase", "扩张期"), scores)
    r = sc.compose(scores, sc.decay_factors(streak), phase)

    wk = hist.get("weekly", [])
    prev_s = wk[-1]["s"] if wk else None
    prev_m = hist.get("last_metrics_mapped")
    b = sc.bottom_score(scores, prev_s, metrics, prev_m) if prev_s and prev_m else {"total": 0}

    eq = sc.equity_anchor(eq_raw["price"], eq_raw["high_52w"], spot["at_record"]) if eq_raw else None
    if eq: eq.update(eq_raw)

    note = optional_note(scores, spot, eq)
    today = bj_today()

    entry = {"period": today, "s": scores, "top": r["total"], "bottom": b["total"],
             "phase": phase, "n50": r["n50"], "n75": r["n75"], "trig": bool(r["triggers"]),
             "conf": "high", "kind": "周度实测", "spot": spot["latest"],
             "wow": round(wow, 2), "note": note}
    hist["weekly"] = [w for w in wk if w["period"] != today] + [entry]
    hist["streak_carryover"] = streak
    hist["last_phase"] = phase
    hist["last_quarterly_asof"] = {k: qin[k].get("asof") for k in
                                   ("capex", "inventory", "demand", "narrative")}
    hist["last_metrics_mapped"] = metrics
    if eq: hist["equity_anchor"] = eq

    sources = [{"title": "TrendForce 现货价（经 Capital & Compute 聚合）", "url": fetcher.SRC_SPOT},
               {"title": "TrendForce 官方现货价页", "url": "https://www.trendforce.com/price/dram/dram_spot"}]

    data = {
        "updated": today, "schema": "v3.1", "top": r["total"], "bottom": b["total"],
        "phase": phase, "stage": r["stage"], "stage_desc": r["stage_desc"],
        "n50": r["n50"], "n75": r["n75"], "triggers": r["triggers"],
        "signals": [{"id": i+1, "name": NAMES[i], "lead": LEADS[i], "score": scores[i],
                     "weight": sc.WEIGHTS[i], "metrics": metrics[i],
                     "fresh": fresh.get(NAMES[i], True)} for i in range(5)],
        "equity_anchor": eq or {}, "spot": spot, "sources": sources, "note": note,
        "quarterly": hist["quarterly"], "weekly": hist["weekly"],
        "disclaimer": "本页面为个人研究用途的公开信息聚合，由程序按固定规则自动生成，"
                      "季度序列为历史规则重建而非实测，可能存在错误或延迟，不构成任何投资建议。",
    }
    payload = json.dumps(data, ensure_ascii=False, indent=1).encode("utf-8")
    print(f"{today}: 五信号={scores} 顶温={r['total']} 底温={b['total']} 相位={phase} "
          f"触发={r['triggers'] or '无'} 股价背离={'是' if (eq and eq['alert']) else '否'}")
    if dry_run:
        print("[dry-run] 未写 history_v3.json / data.json，未上传")
        return
    json.dump(hist, open(HIST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    open(OUT, "wb").write(payload)
    if no_upload:
        print("[跳过上传] 读数已落盘；上传由后续 --upload-only 步骤负责")
        return
    upload(payload)


def upload(content: bytes):
    """推送 data.json 到对象存储。COS_BUCKET 优先，否则回落到云开发 Storage。"""
    if not (TCB_ID and TCB_KEY):
        sys.exit("[错误] TCB_SECRET_ID / TCB_SECRET_KEY 不能为空")
    from qcloud_cos import CosConfig, CosS3Client

    if COS_BUCKET:
        bucket, region = COS_BUCKET, COS_REGION
        domain = f"{COS_BUCKET}.cos.{COS_REGION}.myqcloud.com"
    else:
        if not TCB_ENV:
            sys.exit("[错误] COS_BUCKET 与 TCB_ENV 至少设置一个，否则无处可传")
        from tencentcloud.common import credential
        from tencentcloud.tcb.v20180608 import tcb_client, models
        tcb = tcb_client.TcbClient(credential.Credential(TCB_ID, TCB_KEY), TCB_REGION)
        req = models.DescribeEnvsRequest(); req.EnvId = TCB_ENV
        envs = [e for e in (tcb.DescribeEnvs(req).EnvList or []) if e.EnvId == TCB_ENV]
        if not envs or not envs[0].Storages:
            sys.exit(f"[错误] 未找到环境 {TCB_ENV} 的存储信息"
                     f"（环境已停服/欠费/被回收时同样落到这里，先查云开发控制台）")
        st = envs[0].Storages[0]
        bucket, region, domain = st.Bucket, st.Region, st.CdnDomain

    CosS3Client(CosConfig(Region=region, SecretId=TCB_ID, SecretKey=TCB_KEY)).put_object(
        Bucket=bucket, Key=CLOUD_PATH, Body=content,
        ContentType="application/json; charset=utf-8", CacheControl="max-age=300")
    print(f"上传成功: https://{domain}/{CLOUD_PATH}")


USAGE = """用法: python scripts/update.py [选项]
  （无选项）      抓取 → 打分 → 落盘 → 上传
  --dry-run       只抓取打分并打印，不写文件、不上传（本地预览用）
  --no-upload     抓取打分并落盘，但不上传（上传交给 --upload-only）
  --upload-only   不重新计算，直接把现有 data/data.json 推上去"""

if __name__ == "__main__":
    argv = set(sys.argv[1:])
    unknown = argv - {"--dry-run", "--no-upload", "--upload-only"}
    if unknown:
        sys.exit(f"[错误] 未知参数 {sorted(unknown)}" + chr(10) + USAGE)
    if "--upload-only" in argv:
        if not os.path.exists(OUT):
            sys.exit(f"[错误] {OUT} 不存在，先跑一次不带 --upload-only 的更新")
        upload(open(OUT, "rb").read())
    else:
        main(dry_run="--dry-run" in argv, no_upload="--no-upload" in argv)

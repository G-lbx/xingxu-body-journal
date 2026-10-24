"""Evidence-linked, deterministic body-recomposition guidance (no network or writes).

All dates are interpreted in Asia/Shanghai. Device comparison / inferred records
are never promoted to observations. Window thresholds are product confidence
rules, not clinical diagnostic cutoffs. See docs/health-sources.md.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import math
from statistics import mean


SHANGHAI = timezone(timedelta(hours=8))
FIELDS = {
    "weight": (20, 350), "body_fat": (2, 75),
    "muscle_mass": (1, 200), "skeletal_mass": (1, 150), "waist": (30, 220),
}
SOURCES = [
    {"title": "WHO｜成人身体活动与循序渐进原则", "url": "https://www.who.int/news-room/fact-sheets/detail/physical-activity"},
    {"title": "ISSN｜健康运动成人的蛋白质摄入共识（2017）", "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC5477153/"},
    {"title": "NHS｜如何在一致条件下记录体重", "url": "https://www.england.nhs.uk/long-read/how-to-record-your-weight/"},
    {"title": "CDC｜各年龄段的睡眠建议", "url": "https://www.cdc.gov/sleep/about/index.html"},
    {"title": "BIA 测量研究｜可靠性、生物波动与准确性（2024）", "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC11649400/"},
    {"title": "CDC｜20 岁及以上成人 BMI 分类与筛查局限", "url": "https://www.cdc.gov/bmi/adult-calculator/bmi-categories.html"},
]


def _number(value, low=None, high=None):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(number):
        return None
    if low is not None and number < low or high is not None and number > high:
        return None
    return number


def _time(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.replace(tzinfo=SHANGHAI) if result.tzinfo is None else result.astimezone(SHANGHAI)
    except ValueError:
        return None


def _actual(record):
    if record.get("inferred") is True or record.get("is_estimated") is True:
        return False
    inferred = {"inferred", "derived", "device_comparison", "estimated", "comparison", "推算", "设备对比"}
    # A device_comparison object on a real report is metadata, not its source.
    for key in ("source", "kind", "source_type", "record_type"):
        value = record.get(key)
        if isinstance(value, str) and value.lower() in inferred:
            return False
    return True


def _clean_records(records, today):
    clean, ignored, invalid_values = [], 0, 0
    for record in records or []:
        if not isinstance(record, dict) or not _actual(record):
            ignored += 1
            continue
        timestamp = _time(record.get("measured_at"))
        if timestamp is None or timestamp.date() > today:
            ignored += 1
            continue
        values = {field: _number(record.get(field), *bounds) for field, bounds in FIELDS.items()}
        weight = values["weight"]
        for field in ("muscle_mass", "skeletal_mass"):
            if weight is not None and values[field] is not None and values[field] > weight:
                values[field] = None
        for field in FIELDS:
            if record.get(field) is not None and values[field] is None:
                invalid_values += 1
        if all(value is None for value in values.values()):
            ignored += 1
            continue
        clean.append({"time": timestamp, "day": timestamp.date(), "bmi": _number(record.get("bmi"), 5, 100), **values})
    clean.sort(key=lambda row: row["time"])
    return clean, ignored, invalid_values


def _daily(rows, field):
    by_day = defaultdict(list)
    for row in rows:
        if row[field] is not None:
            by_day[row["day"]].append(row[field])
    return {day: mean(values) for day, values in by_day.items()}


def _week_values(daily, anchor, offset=0):
    end = anchor - timedelta(days=offset * 7)
    start = end - timedelta(days=6)
    return [value for day, value in daily.items() if start <= day <= end]


def _rounded(value):
    return round(value, 2) if value is not None else None


def _metric(rows, field, anchor):
    points = [row for row in rows if row[field] is not None]
    latest = points[-1][field] if points else None
    previous = points[-2][field] if len(points) >= 2 else None
    current = _week_values(_daily(rows, field), anchor)
    prior = _week_values(_daily(rows, field), anchor, 1)
    return {
        "latest": latest, "previous": previous,
        "delta": _rounded(latest - previous) if previous is not None else None,
        "week_mean": _rounded(mean(current)) if current else None,
        "previous_week_mean": _rounded(mean(prior)) if prior else None,
        "week_delta": _rounded(mean(current) - mean(prior)) if len(current) >= 3 and len(prior) >= 3 else None,
        "days_current": len(current), "days_previous": len(prior),
    }


def _action(id_, title, detail, reason, category, icon):
    return {"id": id_, "title": title, "detail": detail, "reason": reason, "category": category, "icon": icon}


def _insight(title, text, tone="neutral"):
    return {"title": title, "text": text, "tone": tone}


def _profile_state(profile):
    age = _number(profile.get("age"), 1, 120)
    missing = []
    if age is None:
        missing.append("实际年龄")
    if _number(profile.get("height"), 80, 250) is None:
        missing.append("身高")
    if profile.get("sex") not in ("male", "female"):
        missing.append("性别")
    if profile.get("training_level") not in ("beginner", "regular", "experienced"):
        missing.append("训练基础")
    if profile.get("health_context") not in ("none", "special"):
        missing.append("健康与运动限制确认")
    if _number(profile.get("training_days"), 0, 7) is None:
        missing.append("每周可训练天数")
    quantitative = (
        age is not None and age >= 18 and profile.get("health_context") == "none"
        and not str(profile.get("limitations") or "").strip()
        and profile.get("training_level") in ("beginner", "regular", "experienced")
    )
    return age, missing, quantitative


def _checkin_summary(checkins, today):
    # One entry per date; the latest submitted entry wins, matching storage upsert.
    days = {}
    for entry in checkins or []:
        if not isinstance(entry, dict):
            continue
        parsed = _time(entry.get("date"))
        if parsed and today - timedelta(days=6) <= parsed.date() <= today:
            days[parsed.date()] = entry
    entries = list(days.values())
    sleeps = [n for item in entries if (n := _number(item.get("sleep"), 0, 24)) is not None]
    strength = sum(item.get("training") in ("strength", "mixed") and (_number(item.get("minutes"), 0, 600) or 0) > 0 for item in entries)
    return {
        "days": len(entries), "sleep_days": len(sleeps), "sleep_mean": mean(sleeps) if sleeps else None,
        "low_energy_days": sum(item.get("energy") == "low" for item in entries), "strength_days": strength,
    }


def _schedule(training_days, quantified, recovery_first):
    positions = {0: set(), 1: {1}, 2: {0, 3}, 3: {0, 2, 4}}[training_days or 0] if quantified else set()
    schedule = []
    for index, day in enumerate(("周一", "周二", "周三", "周四", "周五", "周六", "周日")):
        if index in positions:
            title = "全身力量 · 动作与恢复优先" if recovery_first else "全身力量 · 稳定练习"
            detail = "按已有、熟悉且无痛的动作练习，记录完成情况；恢复不佳时缩短训练或休息，不加重量。" if recovery_first else "覆盖蹲、髋铰链、推、拉等熟悉动作；先掌握技术，完成后仍有余力。连续完成且恢复良好后，再小幅增加一项难度。"
            type_ = "strength"
        elif index == 6:
            type_, title, detail = "review", "周复盘", "核对测量条件、训练表现与恢复；查看周均值，下一周只调整一项习惯。"
        elif quantified:
            type_, title, detail = "recovery", "轻松活动与恢复", "选择舒适的步行或日常活动，打断久坐；有疼痛或明显疲劳时以休息和评估为先。"
        else:
            type_, title, detail = "record", "建立记录与规律作息", "记录今天已有的活动、睡眠和感受；补充个人档案后再细化训练安排。"
        schedule.append({"day": day, "type": type_, "title": title, "detail": detail})
    return schedule


def build_analysis(records, profile=None, checkins=None):
    """Return a JSON-safe, conservative plan derived from actual observations.

    ``week_mean`` is an available-day mean, even when fewer than three days are
    recorded. ``week_delta`` is withheld unless both windows have >= 3 days.
    Metric ``previous`` always means the previous actual nonmissing measurement.
    """
    profile = profile if isinstance(profile, dict) else {}
    now = datetime.now(SHANGHAI)
    today = now.date()
    rows, ignored, invalid_values = _clean_records(records, today)
    anchor = rows[-1]["day"] if rows else today
    age, missing, quantitative = _profile_state(profile)
    metrics = {field: _metric(rows, field, anchor) for field in FIELDS}
    distinct_days = len({row["day"] for row in rows})
    weight = metrics["weight"]
    height = _number(profile.get("height"), 80, 250)
    profile_bmi_raw = weight["latest"] / ((height / 100) ** 2) if weight["latest"] is not None and height is not None else None
    profile_bmi = _rounded(profile_bmi_raw)
    weight_rows = [row for row in rows if row["weight"] is not None]
    weight_stale = bool(weight_rows and (today - weight_rows[-1]["day"]).days > 14)
    device_bmi = weight_rows[-1]["bmi"] if weight_rows else None
    bmi_mismatch = bool(profile_bmi_raw is not None and device_bmi is not None and abs(profile_bmi_raw - device_bmi) >= 1)
    low_bmi = bool(age is not None and age >= 20 and profile_bmi_raw is not None and profile_bmi_raw < 18.5)
    week_delta = weight["week_delta"]
    stage = "review" if week_delta is not None else "building" if distinct_days >= 3 else "baseline"
    stale = bool(rows and (today - anchor).days > 14)
    checkin = _checkin_summary(checkins, today)
    sleep_low = age is not None and age >= 18 and checkin["sleep_days"] >= 3 and checkin["sleep_mean"] < 7
    recovery_first = sleep_low or checkin["low_energy_days"] >= 2
    titles = {"baseline": "先建立你的身体基线", "building": "让记录形成可比较的趋势", "review": "用周趋势调整下一步"}
    title = titles[stage]
    confidence = {"baseline": "基线期 · 暂不足以判断变化", "building": "积累期 · 周对比仍需更多不同日期", "review": "可做周对比 · 身体组成仍需结合训练与腰围"}[stage]
    summary = (
        "先保存第一份真实测量，再逐步补充个人档案与日常记录。" if not rows else
        f"已记录 {distinct_days} 个不同日期。先保持测量条件一致，结合训练表现、腰围和恢复观察减脂增肌进展。"
    )
    insights, actions = [], []
    limitations = ["体脂和肌肉量是体脂秤估算，受水分与测量条件影响；单次变化不能证明脂肪增减或肌肉流失。", "建议由可解释规则生成，展示数据依据与参考来源；基础代谢估算不作为每日摄入目标。"]
    if stage != "review":
        insights.append(_insight("先积累可比较的数据", f"最近两个 7 天窗口分别有 {weight['days_current']} 和 {weight['days_previous']} 天有效体重记录。两边各达到 3 天后才计算周变化；同一天多次测量先取日平均。"))
    else:
        insights.append(_insight("体重周均值", f"最近窗口 {weight['week_mean']:.2f} kg，上个窗口 {weight['previous_week_mean']:.2f} kg，变化 {week_delta:+.2f} kg；覆盖 {weight['days_current']} / {weight['days_previous']} 个不同日期。"))
    actions.append(_action("consistent-measurement", "保持同样的测量条件", "使用同一台秤、同一位置和相近时段，尽量在早晨、穿着相近时记录；不必为追求曲线反复称重。", "NHS 的测量一致性建议；同日记录会先平均后参与周比较。", "measure", "i-scale"))
    if bmi_mismatch:
        insights.insert(0, _insight("设备 BMI 与你的身高不一致", f"按档案身高 {height:g} cm 和体重 {weight['latest']:.2f} kg 计算的 BMI 为 {profile_bmi:.2f}，原报告 BMI 为 {device_bmi:g}。请核对体脂秤档案的身高等设置，原报告数值会保留。", "attention"))
        actions.insert(0, _action("verify-device-profile", "先核对体脂秤个人设置", "确认秤上使用的是你的档案，并核对身高、年龄和性别；改正后留一条备注并重新测量，前后阶段分开理解。", "个人档案计算 BMI 与设备 BMI 相差至少 1，触发一致性核查；不能由此反推并自动改写身高。", "measure", "i-scale"))
        limitations.append("体脂秤档案可能存在不一致，核对设置前暂不对体脂或肌肉估算趋势作改善判断。")
    if low_bmi:
        insights.insert(0, _insight("当前更适合优先增肌与恢复", f"按已填写身高和体重计算 BMI 为 {profile_bmi:.2f}，低于 CDC 对 20 岁及以上成人的 18.5 筛查界值。BMI 只作筛查；建议先核对数据，并以力量进步、充足饮食和恢复为重点。", "attention"))
        actions.insert(0, _action("muscle-recovery-priority", "把近期重点改为增肌与健康", "先维持规律、足量的餐食与可恢复的训练，不主动制造热量缺口。结合腰围、力量表现和身体感受观察；若体重持续偏低或无意下降，可与医生或营养师讨论原因和适合的改善方案。", f"实际年龄 {age:g} 岁，按身高计算 BMI {profile_bmi:.2f}；不采用体脂秤的标准体重或减重标签作为目标。", "nutrition", "i-fork"))
    available_days = _number(profile.get("training_days"), 0, 7)
    if available_days is not None and available_days >= 6:
        insights.append(_insight("每天能训练，也需要安排恢复", f"你填写了每周 {int(available_days)} 天训练。近期重点是保证恢复，并覆盖下肢与全身主要肌群，避免反复高负荷刺激同一肌群。", "attention"))
        actions.append(_action("balance-and-rest", "给训练安排恢复日与下肢内容", "先记录胸、肩、背及下肢各自的训练与疲劳，给重复刺激的肌群留恢复时间；部分训练日可以改为轻活动或休息。确认健康限制后，再按恢复情况细化上下肢安排。", "你的训练频率较高；周计划不把每天可训练等同于每天都应高强度训练。", "recovery", "i-dumbbell"))
    if missing:
        actions.append(_action("complete-profile", "补充个人档案", "请补充：" + "、".join(missing) + "。实际年龄请自行填写，不采用设备的身体年龄。", "年龄、运动基础与健康背景决定哪些建议适用。", "measure", "i-user"))
    if not quantitative:
        if age is not None and age < 18:
            detail = "当前处于生长发育阶段，以规律吃饭、喜欢的日常活动和充足恢复为主；如需调整体型，与监护人及合适的医护或营养专业人士一起制定计划。"
            reason = "已填写年龄不足 18 岁，成人减脂与运动营养定量不适用。"
        elif profile.get("health_context") == "special" or str(profile.get("limitations") or "").strip():
            detail = "保留已有专业指导，记录活动与不适情况；把健康或运动限制与医生、康复或营养专业人士沟通后，再确定训练强度与饮食量。"
            reason = "个人档案注明了需要考虑的健康或运动限制。"
        else:
            detail = "先记录已有的运动、睡眠与精力，保持规律饮食；确认实际年龄、训练基础和健康情况后，再生成适用的训练与营养参考。"
            reason = "当前尚不能确认健康成人运动建议的适用条件。"
        actions.append(_action("baseline-habits", "先把日常习惯记录下来", detail, reason, "recovery", "i-heart"))

    targets = {"protein_min": None, "protein_max": None, "calories": None, "training_days": None, "aerobic_minutes": None}
    training_days = None
    if quantitative:
        available = _number(profile.get("training_days"), 0, 7)
        training_days = min(3, int(available)) if available is not None else 2
        # Two strength days are an initial arrangement for beginners, not a demand.
        if profile.get("training_level") == "beginner":
            training_days = min(training_days, 2)
        targets["training_days"] = training_days
        targets["aerobic_minutes"] = 150
        training_detail = (
            f"按可安排时间先计划每周 {training_days} 天全身力量，相邻力量日留恢复时间。先选熟悉、可控且无痛的动作，记录完成情况；动作稳定且恢复良好后，再小幅增加一项难度。"
            if training_days else "本周尚未安排力量日。先记录日常活动；有时间后，可从熟悉的基础练习开始，再逐步安排规律训练。"
        )
        if recovery_first:
            training_detail += "近期恢复记录提示需要放缓，本周先保持或降低训练量，不增加负荷。"
        actions.append(_action("strength-routine", "把力量训练排进日程", training_detail, "WHO 建议成人每周至少 2 天肌肉强化活动；这里按你的时间和训练基础给出起步安排。", "training", "i-dumbbell"))
        actions.append(_action("daily-activity", "逐步积累有氧活动", "从当前能舒服完成的步行或其他活动开始，逐渐接近每周 150 分钟中等强度活动；这是长期健康参考，不要求本周立刻达标。", "WHO 成人活动指南强调少量活动也有益，并循序增加。", "training", "i-activity"))
        if weight["latest"] is not None and not weight_stale:
            targets["protein_min"] = round(weight["latest"] * 1.4)
            targets["protein_max"] = round(weight["latest"] * 2.0)
            actions.append(_action("protein-reference", "让每餐有蛋白质来源", f"对已确认无特殊健康限制的成人运动者，可参考每日约 {targets['protein_min']}–{targets['protein_max']} g 蛋白质，分配到日常餐食。优先选择普通食物，保留主食、蔬果与适量脂肪；这是一段参考范围，不是强制指标。", f"ISSN 健康运动成人参考为 1.4–2.0 g/kg/日，按最近体重 {weight['latest']:.2f} kg 计算。", "nutrition", "i-fork"))
        else:
            actions.append(_action("balanced-meals", "维持规律、完整的餐食", "每餐安排蛋白质食物、主食和蔬果；更新体重记录后再显示适用的运动营养参考。", "没有近期有效体重，不推算每日蛋白质克数。", "nutrition", "i-fork"))
    else:
        actions.append(_action("balanced-meals", "记录饮食是否规律", "今天简单记录是否按时吃饭、每餐是否有多样食物，以及运动前后的精力和饥饿感。", "现阶段先了解习惯，暂不设置热量缺口或固定体脂目标。", "nutrition", "i-fork"))

    fat_delta, muscle_delta, waist_delta = (metrics[field]["week_delta"] for field in ("body_fat", "muscle_mass", "waist"))
    if not stale and week_delta is not None:
        relative = week_delta / weight["previous_week_mean"]
        if relative < -0.01:
            title = "先核对下降速度与恢复"
            insights.append(_insight("体重周均值下降较明显", f"周均体重下降约 {abs(relative) * 100:.1f}%。这是需要复核的变化信号，不能仅据此区分水分、脂肪和肌肉变化。", "attention"))
            actions.append(_action("review-fast-change", "本周先复核，不再加大减量", "核对测量时段、水分和最近饮食变化；保持规律吃饭与现有训练，记录精力与训练表现。若下降持续且并非有意，或伴随不适，联系医护人员。", f"两个有效窗口的体重周均变化为 {week_delta:+.2f} kg；1% 是产品复核提示线，非诊断标准。", "recovery", "i-heart"))
        elif not low_bmi and not bmi_mismatch and abs(relative) < 0.003 and waist_delta is not None and waist_delta <= -0.5:
            insights.append(_insight("体重接近稳定，腰围记录下降", f"腰围周均变化 {waist_delta:+.2f} cm。可继续结合相同测量方法及训练表现观察，尚不能确认增肌减脂量。", "positive"))
            actions.append(_action("keep-consistency", "继续当前节奏一周", "先保持饮食与训练安排，下一次复盘比较腰围、体重周均及训练表现，不为追求体重下降而追加节食。", "体重周均接近稳定，腰围呈下降信号。", "nutrition", "i-fork"))
        elif not low_bmi and relative > 0.005 and waist_delta is not None and waist_delta >= 0.5:
            insights.append(_insight("体重和腰围同时上升", f"体重周均 {week_delta:+.2f} kg，腰围周均 {waist_delta:+.2f} cm。先检查测量一致性与近期饮食、活动变化。", "attention"))
            actions.append(_action("review-intake-habits", "复盘一项饮食或活动习惯", "记录最近是否增加零食、含糖饮料或久坐时间，选择一项可持续的小调整，保持正常餐食和力量训练，下周再比较。", "两个有效窗口的体重与腰围方向一致，适合复盘习惯，尚不足以估算热量缺口。", "nutrition", "i-fork"))
        if fat_delta is not None:
            insights.append(_insight("体脂秤的体脂趋势", f"体脂率周均变化 {fat_delta:+.2f} 个百分点。结合腰围、训练和测量条件解读，不把变化直接等同于减脂量。"))
        if muscle_delta is not None and muscle_delta < -0.5:
            insights.append(_insight("肌肉估算值需要复核", f"肌肉量周均变化 {muscle_delta:+.2f} kg。水分及测量条件可能影响读数，不能据此确认肌肉流失。", "attention"))
            actions.append(_action("check-muscle-signal", "同时记录训练表现", "在相近条件下复测，并记录熟悉动作的完成情况与恢复；若表现和身体感受也持续变差，优先减轻负担并寻求合适指导。", "肌肉估算周均下降，需用独立信息交叉核对。", "measure", "i-chart"))

    if checkin["days"]:
        insights.append(_insight("最近 7 天执行记录", f"已打卡 {checkin['days']} 天，其中 {checkin['strength_days']} 天记录了力量或混合训练。未打卡日期视为未知，不当作未运动。"))
    if recovery_first:
        pieces = []
        if sleep_low:
            pieces.append(f"{checkin['sleep_days']} 天已记录睡眠平均 {checkin['sleep_mean']:.1f} 小时")
        if checkin["low_energy_days"] >= 2:
            pieces.append(f"{checkin['low_energy_days']} 天自评精力偏低")
        insights.append(_insight("这一周先照顾恢复", "；".join(pieces) + "。今天先保持或降低活动负担，观察恢复。", "attention"))
    sleep_detail = "尽量保持相近的就寝与起床时间，记录睡眠和醒来后的精神状态。"
    if age is not None and age >= 18:
        sleep_detail += "成人通常需要每晚至少 7 小时睡眠，具体需要因年龄与个人情况而异。"
    actions.append(_action("recovery-routine", "给恢复留出时间", sleep_detail + ("近期睡眠或精力记录提示恢复不足，先避免增加训练难度。" if recovery_first else ""), "CDC 睡眠建议；恢复记录会影响本周训练是否递增。", "recovery", "i-moon"))

    if stale:
        title = "先更新近期测量"
        confidence = "记录已超过 14 天 · 当前趋势待更新"
        insights.insert(0, _insight("需要更新记录", f"最新实测日期为 {anchor.isoformat()}，距今天 {(today - anchor).days} 天；图中窗口属于历史记录，不能代表近期状态。", "attention"))
    if weight_stale:
        limitations.append("最新体重已超过 14 天，暂不据此给出每日蛋白质克数。")
        if not stale:
            insights.insert(0, _insight("体重记录需要更新", f"最近虽然更新了其他指标，但最新有效体重来自 {weight_rows[-1]['day'].isoformat()}。更新体重后再显示蛋白质克数参考。", "attention"))
    if ignored or invalid_values:
        insights.append(_insight("已排除不可比较的数据", f"统计忽略了 {ignored} 条推算、无效或未来记录，以及 {invalid_values} 个越界或不符合基本关系的字段；请检查原始记录。", "attention"))
    if stage == "baseline":
        limitations.append("当前实测天数少，只生成基线与习惯计划，不判定已经减脂或增肌。")
    if low_bmi:
        title = "优先增肌、充足饮食与恢复"
        summary = f"按你的身高计算 BMI 为 {profile_bmi:.2f}。先核对设备档案，以力量进步、规律餐食和恢复为重点；本阶段不安排主动减重。" if bmi_mismatch else f"按你的身高计算 BMI 为 {profile_bmi:.2f}。以力量进步、规律餐食和恢复为重点，本阶段不安排主动减重。"
    return {
        "stage": stage, "title": title, "summary": summary, "confidence": confidence,
        "missing_profile": missing, "metrics": metrics, "insights": insights, "actions": actions,
        "weekly": {
            "title": "下一周 · 稳定记录与恢复" if not quantitative else "下一周 · 力量、活动与恢复",
            "summary": "按你的实际日程移动训练日，力量日之间留恢复时间；每周复盘后再调整一项。" if quantitative else "先建立可比较的记录，补齐档案；已有专业指导优先。",
            "schedule": _schedule(training_days, quantitative, recovery_first),
            "review_date": (today + timedelta(days=7)).isoformat(),
        },
        "targets": targets, "sources": [dict(source) for source in SOURCES], "limitations": limitations,
        "window": {"start": (anchor - timedelta(days=6)).isoformat(), "end": anchor.isoformat(), "previous_start": (anchor - timedelta(days=13)).isoformat(), "previous_end": (anchor - timedelta(days=7)).isoformat()},
        "data_quality": {"valid_records": len(rows), "distinct_days": distinct_days, "ignored_records": ignored, "invalid_values": invalid_values, "profile_bmi": profile_bmi, "device_bmi": device_bmi, "bmi_mismatch": bmi_mismatch, "low_bmi": low_bmi},
        "generated_at": now.isoformat(timespec="seconds"),
    }

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深圳大学公文通「只报大事」日报生成器
================================================
设计思路（三层）
----------------
1. 先按「这条信息对你有没有用」分类，而不是先过滤再排序。
   因为「宣讲会」和「求职技巧讲座」都是"就业"，但一个有时间地点、
   一个只是软文，混在一起排序必然出错。

2. 分成四块，各自有各自的判断标准：
   ⚠️ 校园环境   —— 影响你今天的行动（停水停电、封路、场馆关闭）
   🔴 要办的事   —— 有硬截止，不办会吃亏（报名、缴费、选课、学位）
   💼 就业       —— 招聘会、宣讲会、选调、公务员、实习、就业手续
   💰 机会与资助 —— 访学、交换、竞赛、奖助、补助、贷款

3. 宁可当天报「无事」，也不拿无聊通知凑数。

用法：
    python notice_daily.py                  # 过去 24 小时
    python notice_daily.py --range 7d       # 过去一周
    python notice_daily.py --all            # 调试：看每条的去留和分数
    python notice_daily.py --no-detail      # 不抓正文，快很多
    python notice_daily.py --level ug       # 按本科生标准跑
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date

_HERE = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = (os.path.dirname(_HERE) if os.path.basename(_HERE) == "scripts" else _HERE)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# ================================================================ 一票否决
# 这些词一出现就丢，不参与分类也不参与打分

DROP_ANY = [
    # --- 别人的学位流程，一天能刷好几条 ---
    "答辩公告", "答辩安排", "预答辩", "开题报告会", "中期考核", "期满考核",
    # --- 新闻稿：事已经办完了，看了没用 ---
    "【通讯】", "通讯】", "成功举办", "顺利举办", "顺利举行", "成功举行",
    "圆满结束", "圆满举办", "圆满落幕", "顺利开展", "成功开展",
    "顺利召开", "成功召开", "顺利闭幕", "研学", "访企拓岗", "升旗仪式",
    "主题党日", "团日活动", "青马", "座谈会", "经验分享", "交流会",
    "启动仪式", "开班仪式", "颁奖典礼", "总结大会", "动员大会", "汇报活动",
    "成功入选", "喜报",
    # --- 名单公示：只有名单上的人关心 ---
    "名单公示", "名单的公示", "拟获奖名单", "拟推荐名单", "评选公示",
    "获奖名单", "推荐名单", "公示名单", "结果公示", "拟聘用", "拟录用",
    # --- 科普、软文 ---
    "知多少", "科普", "一问一答", "小课堂",
    # --- 面向教师/管理员 ---
    "教师培训", "教师发展", "师资", "教学名师", "教研项目",
    "系统漏洞", "安全漏洞",
    "项目申报", "申报指南", "研发计划", "重点专项", "基金项目",
    "博士后", "研究生导师", "博士生导师",
    # --- 求职软文（注意：真正的招聘信息不在这里）---
    "求职技巧", "求职面试", "面试技巧", "面试通关", "简历", "职业规划",
    "生涯规划", "就业指导", "就业力", "训练营", "求职必修课",
    "就业系列工作",
]

DROP_BY_LEVEL = {
    "pg": ["本科毕业论文", "本科生学科竞赛", "推免", "保研", "辅修",
           "双学位", "转专业", "本科毕业生", "本科教学", "卓越班", "实验班"],
    "ug": ["研究生院", "学位论文", "博士", "硕士", "研究生科研", "研究生学业"],
    "phd": [],
}

DROP_CATEGORIES = ["讲座"]

# ================================================================ 四类判断

# 💼 就业：出现这些 = 真有具体信息（招聘/岗位/报考/手续）
JOB_HARD = [
    # 企业招聘
    "招聘会", "宣讲会", "双选会", "供需见面", "校园招聘", "专场招聘",
    "招聘信息", "岗位招聘", "诚聘", "实习生", "实习岗", "实习机会",
    "名企", "校招", "空中宣讲", "网申", "学生助理", "助管岗位",
    # 体制内
    "选调", "公务员", "事业单位", "军队文职", "三支一扶", "西部计划",
    "人才引进", "基层就业", "定向招录", "国企", "央企",
    # 就业手续（毕业季硬事）
    "三方协议", "报到证", "派遣", "档案", "户口", "就业推荐表",
    "就业协议", "离校手续",
    # 升学路径（也是就业选择的一种）
    "联合培养", "联合学位", "3+1+1", "出国留学", "留学项目",
]

# 就业类里的软文：只有"讲座/分享"没有"具体招聘"的，一律不算就业信息
JOB_HARD_ANCHOR = ("宣讲会", "招聘会", "双选会", "供需见面", "校园招聘",
                   "专场招聘", "招聘信息", "岗位招聘", "选调", "公务员",
                   "事业单位", "文职", "三支一扶", "西部计划", "人才引进")

# 校园环境：影响今天出门/用水用电
ENV_WORDS = [
    "停水", "停电", "停网", "断网", "封闭", "封路", "暂停开放",
    "临时关闭", "闭馆", "开放时间", "施工", "维修", "搬迁",
    "台风", "暴雨", "寒潮", "预警", "食堂", "校车", "班车",
    "宿舍", "调宿", "退宿", "住宿", "门禁", "校园卡", "一卡通",
    "放假", "节假日", "校历", "开学", "调整", "停止营业", "临时停",
]

# 🔴 要办的事：有截止、要动手
DUE_WORDS = [
    "选课", "退课", "补选", "重修", "考试安排", "补考", "缓考",
    "四六级", "准考证", "成绩", "学籍", "注册", "报到", "缴费",
    "学分", "培养方案", "教学安排", "调课", "停课", "补课",
    "图像采集", "学位申请", "盲审", "论文提交", "开题通知",
    "报名", "截止", "提交材料", "确认", "办理",
]

# 💰 机会与资助
GAIN_WORDS = [
    "交换", "访学", "公派", "留学", "资助", "奖学金", "助学金",
    "助学贷款", "困难补助", "补助", "竞赛", "创新实践", "创业",
    "学术会议", "会议资助", "医保", "退费", "三助", "助管",
]

# 打分用的加减分（用于 DUE / GAIN 内部排序）
BOOST = {
    "截止": 5, "选课": 5, "退课": 5, "报名": 4, "缴费": 4, "注册": 4,
    "补考": 5, "考试安排": 5, "四六级": 5, "图像采集": 5, "盲审": 5,
    "学位": 4, "毕业": 4, "学籍": 4, "论文": 3, "学分": 3,
    "停水": 5, "停电": 5, "停网": 5, "断网": 5, "封路": 4, "闭馆": 4,
    "放假": 5, "节假日": 4, "校历": 4, "开学": 4, "校车": 4, "班车": 4,
    "食堂": 4, "宿舍": 4, "门禁": 4, "校园卡": 5, "调整": 2, "暂停": 2,
    "台风": 5, "暴雨": 4, "暂停开放": 4, "临时关闭": 4,
    "助学贷款": 5, "困难补助": 5, "医保": 4, "奖学金": 3, "资助": 3,
    "交换": 4, "访学": 4, "公派": 4, "竞赛": 3,
}

PENALTY = {
    "讲座": -3, "论坛": -3, "分享": -3, "报告会": -3, "研讨会": -3,
    "沙龙": -2, "征文": -2, "征稿": -3, "倡议书": -3, "风采": -3,
    "活动": -2, "大赛": -1, "培训": -1,
}

CORE_PUBLISHERS = {
    "教务部": 4, "学生部": 4, "后勤保障部": 4, "党政办公室": 3,
    "研究生院": 4, "学位办": 4, "招生办公室": 3, "计划财务部": 3,
    "国际交流与合作部": 3, "保卫部": 3, "校医院": 3, "信息中心": 3,
    "图书馆": 3, "团委": 2, "组织统战部": 3, "就业": 4,
}

THRESHOLD = 6          # DUE / GAIN 的入榜线
CAP = {"env": 4, "due": 6, "job": 7, "acad": 3, "gain": 4}

# ================================================================ 人话注释
# 每条公告除了「什么时候、在哪」，再补一句人话：这是干嘛的、不管会怎样。
# 键是标题里的关键词，值是一句可以直接读出来的大白话。

HUMAN = {
    # —— 学业节点 ——
    "选课": "下学期上什么课，自己上网挑。手慢的话热门的几分钟就没了，只剩没人要的。",
    "退课": "不想上的课要自己在系统里退掉。不退就挂着，最后算你缺考。",
    "补选": "错过正常选课后的最后一次补选机会。这趟赶不上就得等下学期。",
    "重修": "挂了的课重新修。要在系统里自己报，不会自动帮你加。",
    "考试安排": "期末哪天考哪门、在哪个教室。提前知道才好安排复习和抢自习位。",
    "补考": "挂科后的补考。时间地点和正常考试不一样，容易记错。",
    "缓考": "实在考不了可以申请缓考，但要在考前办手续，考完再申请一律不批。",
    "四六级": "英语四六级报名。名额有限，而且有些岗位和毕业要求会卡这个证。",
    "成绩": "成绩出来了，或者可以申请复核。对分数有疑问的，复核有时间窗。",
    "学籍": "学籍信息核对。错了会影响毕业证、奖学金、贷款，必须自己确认一遍。",
    "注册": "每学期报到注册。不注册会被按休学处理，别拖到最后一天。",
    "缴费": "学费住宿费。逾期可能影响选课和毕业手续。",
    "培养方案": "你要修哪些课、修多少学分才能毕业。对着它查自己还缺什么。",
    "学分": "学分统计。不够会影响毕业，早点发现还能补。",
    "教学安排": "上课时间地点、教学周调整。开学第一周最容易踩错教室。",
    "调课": "某节课换了时间或教室。不去看通知就会白跑一趟。",
    "停课": "某节课临时不上。白跑一趟很亏。",
    # —— 毕业流程（离你还有几年，年级不够时会被过滤）——
    "图像采集": "毕业证和学信网上那张证件照。不去拍，毕业手续就卡在这一步，补拍很麻烦。",
    "盲审": "论文送外校匿名评审。这一步不过就得延期毕业，是毕业流程里最硬的一关。",
    "学位申请": "正式申请学位。材料一堆，缺一样就得下次再说。",
    "论文提交": "论文定稿上传。有查重和格式要求，卡在最后一刻很容易出错。",
    "开题": "论文选题要过导师和答辩组。开题不过，后面全往后推。",
    "中期": "中期检查。走个流程，但不过也会影响进度。",
    "答辩": "论文答辩的时间地点。要提前准备 PPT 和讲稿。",
    "离校手续": "毕业离校前要盖章的一串手续。少跑一个章就领不到毕业证。",
    "三方协议": "毕业生、学校、公司三方签的就业协议。签了才算正式定下来。",
    "报到证": "去单位报到用的凭证。丢了补办很麻烦。",
    "档案": "你的人事档案去向。寄错了将来考公、入职都会卡。",
    "户口": "户口迁移。要自己办，学校不会替你决定。",
    # —— 校园生活（时效性最强）——
    "停水": "这片区域要停水。提前接两桶水，别等到晚上洗澡才发现。",
    "停电": "要停电。手机电脑提前充好电，冰箱里的东西注意。",
    "停网": "网络要断。赶 ddl 的话提前把资料下好。",
    "断网": "网络要断。赶 ddl 的话提前把资料下好。",
    "封路": "校区里某段路围起来施工。骑车开车得绕行，走路可能多绕几分钟，别按老路线走。",
    "施工": "附近在施工。可能有噪音、尘土、临时围挡，绕开走。",
    "暂停开放": "场地暂时关了。想去的先别去，免得白跑。",
    "临时关闭": "场地或服务临时关停。去之前确认一下。",
    "闭馆": "图书馆或场馆关门。复习周遇上这个最坑，提前换个地方。",
    "开放时间": "开放时间有变。按老时间去可能吃闭门羹。",
    "食堂": "食堂营业安排有变。可能停业检修或者换时间。",
    "宿舍": "宿舍相关，可能是维修、调宿、检查。跟你住的地方直接相关。",
    "台风": "台风来了。会停课、断水断电、封楼，物资提前备好，别出门。",
    "暴雨": "暴雨预警。低洼路段会积水，出门前看一眼。",
    "医保": "大学生医保，看病报销用的。有参保时间和报销流程，别等生病才想起来。",
    "校园卡": "校园卡（吃饭、门禁、洗澡都用它）。丢了或者系统升级都会影响日常。",
    # —— 钱 ——
    "奖学金": "评奖学金。要自己交材料，不交等于放弃，别以为会自动评给你。",
    "助学金": "助学金。通常要提交家庭情况材料，有截止日期。",
    "助学贷款": "助学贷款。涉及续贷和还款，手续有时间点，错过影响征信。",
    "困难补助": "临时困难补助。家里遇到事可以申请，材料要如实填。",
    "补助": "有补助可以申请。要自己动手，不会自动到账。",
    # —— 就业 ——
    "宣讲会": "某个单位来学校讲他们招什么人、什么待遇。现场能问到网上查不到的东西，还能递简历。",
    "招聘会": "一批单位集中来学校摆摊。一次能投十几家，比一家家网申快得多。",
    "双选会": "企业和学生面对面双向选择。带够简历，穿得像样点。",
    "供需见面": "企业和学生面对面双向选择。带够简历。",
    "校园招聘": "企业针对应届生的正式招聘。流程长，越早投越好。",
    "专场招聘": "某家单位专门来招某个方向的人。对口的话命中率比海投高很多。",
    "实习": "实习岗位。读书期间攒一段实习，找工作时简历才不空。",
    "学生助理": "校内勤工助学的岗位。时间灵活、离得近，还能认识老师。",
    "选调": "选调生，公务员里的重点培养通道。门槛高但起点好，报名窗口很短。",
    "公务员": "公务员考试相关信息。岗位表出来到报名截止只有几天，容易错过。",
    "事业单位": "事业单位招聘。比公务员竞争小一些，同样有硬性报名时间。",
    "人才引进": "地方引才计划。通常给编制和补贴，条件看具体公告。",
    # —— 深造与机会 ——
    "访学": "去海外高校交流一段时间，通常有资助。名额和截止日期都紧，错过等一年。",
    "交换": "校际交换项目。能换学分，也能给履历加东西，但要提前申请。",
    "公派": "国家公派留学。资助力度大，申请周期长，要提前一年准备。",
    "联合培养": "和国外高校联合的项目，可能拿双学位或者出去读一段。门槛和语言要求要提前查。",
    "联合学位": "和国外高校联合的项目，可能拿双学位或者出去读一段。门槛和语言要求要提前查。",
    "3+1+1": "和国外高校联合的项目，可能拿双学位或者出去读一段。门槛和语言要求要提前查。",
    "留学": "出国留学相关信息。语言成绩和申请材料都得提前很久准备。",
    "竞赛": "学科竞赛。拿奖对评奖学金、保研、简历都有用，报名通常要组队。",
    "大赛": "学科竞赛。拿奖对评奖学金、评优、简历都有用，报名要组队并且有截止时间。",
    "学术报告": "本院请人来讲某个研究方向。能听到前沿进展，也是跟导师、同学混熟的机会。",
    "学术讲座": "本院请人来讲某个研究方向。能听到前沿进展，也是跟导师、同学混熟的机会。",
    "前沿论坛": "本院请人来讲某个研究方向。能听到前沿进展，也是跟导师、同学混熟的机会。",
    "图书馆": "图书馆的通知，可能涉及开放时间、借阅规则、数据库权限。",
}

# 这些词更具体，命中它们时不要用「宣讲会」那类泛化解释
HUMAN_STRONG = {
    "联合培养", "联合学位", "3+1+1", "访学", "交换", "公派", "留学", "留学项目",
    "选调", "公务员", "事业单位", "人才引进", "军队文职",
    "实习", "学生助理", "助管", "岗位招聘",
    "竞赛", "大赛", "奖助", "奖学金", "助学金", "补助", "助学贷款", "困难补助",
    "图像采集", "盲审", "学位申请", "论文提交", "开题", "答辩",
    "停水", "停电", "停网", "断网", "封路", "台风", "暴雨", "闭馆",
    "选课", "退课", "四六级", "补考", "缓考", "考试安排",
}

# 类别级别的兜底解释（没命中上面任何词时用）
HUMAN_BY_SECTION = {
    "env": "校园环境有变化，会直接影响你今天的行动路线。",
    "due": "有明确截止的事，错过要等下一轮。",
    "job": "具体的招聘或宣讲信息，有单位、有时间地点，想去就能去。",
    "acad": "本院组织的学术活动，对科研和对导师的印象都有帮助。",
    "gain": "可以主动争取的机会，通常有名额和截止日期。",
}

# 只跟毕业年级相关的流程词：离毕业还早时自动不报
GRAD_FLOW = ["图像采集", "学位申请", "盲审", "论文提交", "预答辩",
             "离校手续", "三方协议", "报到证", "派遣", "档案",
             "户口", "就业推荐表", "毕业"]

# 就业类再细分，用于按「关注方向」过滤
JOB_GROUP = {
    "campus": ["招聘会", "双选会", "供需见面", "校园招聘", "专场招聘", "招聘信息",
               "岗位招聘", "宣讲会", "校招", "名企", "空中宣讲", "网申"],
    "intern": ["实习", "学生助理", "助管", "助理岗位"],
    "gov": ["选调", "公务员", "事业单位", "军队文职", "三支一扶", "西部计划",
            "人才引进", "定向招录", "基层就业"],
    "abroad": ["联合培养", "联合学位", "3+1+1", "出国留学", "留学项目",
               "访学", "交换", "公派"],
}

INTEREST_TO_GROUP = {"校招": "campus", "实习": "intern",
                     "考公": "gov", "深造": "abroad"}


# ================================================================ 调 CLI


def resolve_cli():
    """Windows 上 PATH 里的 szu-cli 可能只是个 sh 脚本，Python 跑不了，
    所以优先定位 src/cli.js 交给 node 执行。"""
    env = os.environ.get("SZU_CLI_JS")
    if env and os.path.isfile(env):
        return [shutil.which("node") or "node", env]

    for n in (["szu-cli.cmd", "szu-cli.exe", "szu-cli.bat"] if os.name == "nt" else ["szu-cli"]):
        p = shutil.which(n)
        if p:
            return [p]

    roots = []
    shim = shutil.which("szu-cli")
    if shim:
        roots.append(os.path.dirname(shim))

    node = shutil.which("node") or "node"
    for r in roots:
        js = os.path.join(r, "node_modules", "szu-cli", "src", "cli.js")
        if os.path.isfile(js):
            return [node, js]

    try:
        g = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=30)
        js = os.path.join(g.stdout.strip(), "szu-cli", "src", "cli.js")
        if os.path.isfile(js):
            return [node, js]
    except Exception:
        pass

    sys.exit("找不到 szu-cli。请确认已安装，或设置 SZU_CLI_JS 指向 src/cli.js。")


def run_cli(args, timeout=240):
    cmd = resolve_cli() + args
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except FileNotFoundError:
        sys.exit("找不到 szu-cli，请确认已安装并加入 PATH。")
    except subprocess.TimeoutExpired:
        sys.exit("szu-cli 超时（%ss），学校服务或网络可能有问题。" % timeout)

    raw = (p.stdout or "").strip()
    if not raw:
        sys.exit("szu-cli 没有输出。stderr: " + (p.stderr or "")[:300])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit("szu-cli 返回的不是 JSON：\n" + raw[:500])
    if not data.get("ok"):
        err = data.get("error", {})
        sys.exit("szu-cli 报错 [%s] %s" % (err.get("code"), err.get("message")))
    return data.get("data", {})


# ================================================================ 正文要点


_VIEW_CACHE = {}


def _view(nid):
    k = str(nid)
    if k in _VIEW_CACHE:
        return _VIEW_CACHE[k]
    d = {}
    try:
        d = run_cli(["notice", "view", k], timeout=120)
    except SystemExit:
        d = {}
    _VIEW_CACHE[k] = {"text": d.get("contentText") or "",
                      "atts": d.get("attachments") or []}
    return _VIEW_CACHE[k]


def safe_view(nid):
    """取正文，带缓存（同一篇只抓一次）。"""
    return _view(nid)["text"]


def view_atts(nid):
    return _view(nid)["atts"]


# 结构化字段：让邮件自己说清楚，不用点进去登录
FIELD_RULES = [
    ("时间", [r"时间[:：]\s*([^。；\n]{3,50})",
              r"于\s*(\d{1,2}月\d{1,2}日[^。；\n]{0,34})"]),
    ("地点", [r"地点[:：]\s*([^。；\n]{2,40})",
              r"地址[:：]\s*([^。；\n]{2,40})",
              r"地点为\s*([^。；\n]{2,40})"]),
    ("截止", [r"截止(?:时间|日期)?[:：]\s*([^。；\n]{3,40})",
              r"(\d{1,2}月\d{1,2}日[^。；\n]{0,4}前(?:完成|提交|报名|交)[^。；\n]{0,16})",
              r"(\d{1,2}月\d{1,2}日[^。；\n]{0,6}(?:关闭|截止))"]),
    ("谁能参加", [r"对象[:：]\s*([^。；\n]{4,52})",
                 r"面向([^。；\n]{4,52})",
                 r"参加人员[:：]\s*([^。；\n]{4,52})",
                 r"条件[:：]\s*([^。；\n]{4,52})"]),
    ("怎么报名", [r"报名方式[:：]\s*([^。；\n]{4,60})",
                 r"(?:登录|进入|访问|扫描)[^。；\n]{3,24}(?:系统|平台|小程序|二维码|网址)[^。；\n]{0,20}"]),
    ("要交什么", [r"需?(?:提交|携带|准备)([^。；\n]{4,52})",
                 r"材料[:：]\s*([^。；\n]{4,52})"]),
    ("找谁问", [r"联系人[:：]\s*([^。；\n]{2,26})",
               r"联系电话[:：]?\s*([^。；\n]{5,26})",
               r"(?:电话|联系方式)[:：]?\s*([0-9\-—()（）]{7,20})"]),
]

FIELD_LIMIT = {"env": 2, "due": 4, "job": 3, "acad": 2, "gain": 4}

# 值里混进下一栏时要在这里切断
_FIELD_CUT = re.compile(
    r"(?:\s+[一二三四五六七八九十]、|\s*（[一二三四五六七八九十]）|\s+\d+[.、]\s*"
    r"|\s+附\s*件|\s+地点[:：]|\s+时间[:：]|\s+对象[:：]|\s+联系人[:：]"
    r"|宣讲对象[:：]|宣讲人|报告人|主办单位|承办单位|备注[:：])")

_LABEL_LEN = {"时间": 40, "地点": 26, "截止": 34, "谁能参加": 44,
              "怎么报名": 46, "要交什么": 44, "找谁问": 22}


def _clean_field(v, label):
    v = _FIELD_CUT.split(v)[0]
    v = re.sub(r"\s{2,}", " ", v).strip(" ：:，,。；;·、-")
    n = _LABEL_LEN.get(label, 44)
    if len(v) > n:
        v = v[:n] + "…"
    return v


def extract_fields(text, atts=None):
    """把正文里的关键字段抠出来，让邮件不点链接也能看清。"""
    flat = _flatten(text)
    if not flat:
        return []
    out, used, seen = [], set(), set()
    for label, pats in FIELD_RULES:
        if label in used:
            continue
        for p in pats:
            m = re.search(p, flat)
            if m:
                v = _clean_field((m.group(1) if m.groups() else m.group(0)) or "", label)
                if len(v) < 2:
                    continue
                sig = v[:8]
                if sig in seen:      # 和前面某个字段重复了，跳过
                    break
                out.append((label, v))
                used.add(label)
                seen.add(sig)
                break
    if atts:
        names = [a.get("name") or a.get("title") or "" for a in atts if isinstance(a, dict)]
        names = [n for n in names if n]
        hint = "、".join(names[:2]) if names else "%d 个" % len(atts)
        out.append(("附件", hint + "（细节可能在附件里）"))
    return out



def _flatten(text):
    """压平空白、去掉末尾落款。注意：不能按「附件」截断——
    有的公告截止时间就写在附件清单后面。"""
    flat = re.sub(r"\s+", " ", text or "").strip()
    flat = re.sub(r"\S{0,12}\s*\d{4}年\d{1,2}月\d{1,2}日\s*$", "", flat).strip()
    return flat


DATE_RE = re.compile(r"(\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[:：]\d{2})")


def key_point(text, limit=120):
    """从正文挑最像「什么时候、在哪、怎么弄」的一句。"""
    flat = _flatten(text)
    if not flat:
        return ""
    GOOD = ("截止", "前完成", "报名", "登录", "地点", "方式", "携带", "提交",
            "填写", "办理", "封闭", "暂停", "开放", "封路", "采集", "时间")
    BAD = ("据了解", "据中国地震台网", "为了", "现将", "特此", "如遇天气",
           "背景", "意义", "指出", "强调", "希望", "欢迎", "届时",
           "联系人", "联系电话", "咨询电话", "谅解", "不便", "顺延")
    best, best_s = None, -99
    for seg in re.split(r"(?<=[。；！?])", flat):
        seg = seg.strip().lstrip("一二三四五六七八九十、（）() ").strip()
        if len(seg) < 8:
            continue
        # 纯附件清单、纯文件名，跳过
        if re.search(r"\.(docx?|pdf|xlsx?|zip|rar|jpe?g|png)", seg) or seg.startswith("附件"):
            continue
        s = (4 if DATE_RE.search(seg) else 0)
        s += 2 * sum(1 for k in GOOD if k in seg)
        s -= 3 * sum(1 for k in BAD if k in seg)
        if 20 <= len(seg) <= limit + 40:
            s += 1
        if s > best_s:
            best, best_s = seg, s
    if best and best_s > 0:
        return best[:limit] + ("…" if len(best) > limit else "")
    return flat[:limit] + ("…" if len(flat) > limit else "")


# ================================================================ 附件解析
# 没有第三方库，docx/xlsx/pptx 本质是 zip + XML，可以直接抽字。
# PDF 只能尽力而为（中文 PDF 常是自定义编码，抽不出来就放弃，不乱猜）。

def _docx_text(path):
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
    except Exception:
        return ""
    xml = xml.replace("</w:p>", "\n").replace("</w:tr>", "\n").replace("</w:tc>", "\t")
    t = re.sub(r"<[^>]+>", "", xml)
    t = (t.replace("&amp;", "&").replace("&lt;", "<")
          .replace("&gt;", ">").replace("&quot;", '"'))
    return re.sub(r"\n{2,}", "\n", t).strip()


def _pptx_text(path):
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            names = sorted(n for n in z.namelist()
                           if n.startswith("ppt/slides/slide") and n.endswith(".xml"))
            out = []
            for n in names:
                xml = z.read(n).decode("utf-8", "ignore")
                out.append(re.sub(r"<[^>]+>", " ", xml))
            t = "\n".join(out)
    except Exception:
        return ""
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"\n{2,}", "\n", t)).strip()


def _xlsx_text(path):
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            shared = []
            if "xl/sharedStrings.xml" in z.namelist():
                sx = z.read("xl/sharedStrings.xml").decode("utf-8", "ignore")
                shared = [re.sub(r"<[^>]+>", "", m)
                          for m in re.findall(r"<si>(.*?)</si>", sx, re.S)]
            out = []
            for n in sorted(x for x in z.namelist() if x.startswith("xl/worksheets/")):
                sx = z.read(n).decode("utf-8", "ignore")
                for row in re.findall(r"<row[^>]*>(.*?)</row>", sx, re.S):
                    cells = []
                    for c in re.findall(r"<c[^>]*?(?:t=\"s\")?[^>]*>(.*?)</c>", row, re.S):
                        v = re.search(r"<v>(.*?)</v>", c)
                        if not v:
                            continue
                        val = v.group(1)
                        if val.isdigit() and shared and int(val) < len(shared):
                            val = shared[int(val)]
                        cells.append(val)
                    if cells:
                        out.append(" | ".join(cells))
            t = "\n".join(out)
    except Exception:
        return ""
    return t.strip()


def _pdf_text(path):
    """尽力而为：解压流后抓 Tj/TJ 里的字符串。中文常抽不出来，抽不出就返回空。"""
    import zlib
    try:
        raw = open(path, "rb").read()
    except Exception:
        return ""
    chunks = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", raw, re.S):
        try:
            data = zlib.decompress(m.group(1))
        except Exception:
            continue
        for t in re.findall(rb"\((?:[^()\\]|\\.)*\)", data):
            try:
                chunks.append(t[1:-1].decode("latin-1"))
            except Exception:
                pass
    txt = " ".join(chunks)
    cjk = len(re.findall(r"[\u4e00-\u9fa5]", txt))
    if cjk < 30:          # 抽出来基本是乱码或纯英文，意义不大
        return ""
    return txt


def attachment_text(path):
    low = (path or "").lower()
    if low.endswith(".docx"):
        return _docx_text(path)
    if low.endswith(".pptx"):
        return _pptx_text(path)
    if low.endswith(".xlsx"):
        return _xlsx_text(path)
    if low.endswith(".pdf"):
        return _pdf_text(path)
    return ""


KEY_LINE = re.compile(
    r"(截止|截至|名额|人数|条件|资格|要求|材料|携带|报名|申请|时间|地点|"
    r"对象|面向|待遇|补贴|薪酬|岗位|联系|电话|邮箱|提交|面试|笔试|考核)")
BAD_LINE = re.compile(r"^(姓\s*名|学\s*号|照\s*片|备\s*注|签\s*字|日\s*期)$")
FORM_LINE = re.compile(r"□|☐|是\s*/\s*否|填写|申请人签名")


def key_lines(text, limit=5):
    """从附件全文里挑几行真正有用的（时间、名额、条件、材料、联系方式）。"""
    if not text:
        return []
    out, seen = [], set()
    for raw in text.splitlines():
        line = re.sub(r"\s{2,}", " ", raw).strip(" \t·、|")
        if len(line) < 6 or BAD_LINE.match(line):
            continue
        if not KEY_LINE.search(line) or FORM_LINE.search(line):
            continue
        sig = line[:12]
        if sig in seen:
            continue
        seen.add(sig)
        out.append(line[:64] + ("…" if len(line) > 64 else ""))
        if len(out) >= limit:
            break
    return out


ATT_DIR = "atm_cache"
ATT_BUDGET = [4]      # 每次运行最多解析几篇附件


def attachment_digest(nid, atts):
    """下载并解析附件，返回关键行列表。失败就当没有。"""
    if not atts or ATT_BUDGET[0] <= 0:
        return []
    here = BASE_DIR
    cache_dir = os.path.join(here, ATT_DIR)
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, "%s.txt" % nid)
    if os.path.isfile(cache_file):
        try:
            with open(cache_file, encoding="utf-8") as f:
                return [x for x in f.read().splitlines() if x]
        except Exception:
            pass

    lines = []
    for a in atts[:2]:
        idx = a.get("index")
        name = a.get("name") or ""
        if not idx:
            continue
        if not re.search(r"\.(docx?|pdf|xlsx?|pptx?|txt)$", name, re.I):
            continue
        if ATT_BUDGET[0] <= 0:
            break
        try:
            r = run_cli(["notice", "download", str(nid), "--index", str(idx),
                         "--dir", cache_dir], timeout=180)
        except SystemExit:
            continue
        saved = r.get("savedPath") or ""
        saved = saved if os.path.isabs(saved) else os.path.join(here, saved)
        if not os.path.isfile(saved):
            continue
        ATT_BUDGET[0] -= 1
        try:
            lines += key_lines(attachment_text(saved), limit=5)
        finally:
            try:
                os.remove(saved)      # 只留抽出来的文字，原件立刻删掉
            except Exception:
                pass

    # 去重并截断
    uniq, seen = [], set()
    for l in lines:
        if l[:12] in seen:
            continue
        seen.add(l[:12])
        uniq.append(l)
    uniq = uniq[:6]
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            f.write("\n".join(uniq))
    except Exception:
        pass
    return uniq


# ================================================================ 待办清单

def _pending_path():
    return os.path.join(BASE_DIR, "pending.json")


def load_pending():
    p = _pending_path()
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return (json.load(f) or {}).get("items") or {}
    except Exception:
        return {}


def save_pending(items):
    try:
        with open(_pending_path(), "w", encoding="utf-8") as f:
            json.dump({"items": items}, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


MONTH_DAY = re.compile(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日")


def infer_due(*texts):
    """从「截止」类文字里推断出具体截止日。返回 date 或 None。"""
    today = date.today()
    for t in texts:
        if not t:
            continue
        m = MONTH_DAY.search(t)
        if not m:
            continue
        y = int(m.group(1)) if m.group(1) else today.year
        mo, dd = int(m.group(2)), int(m.group(3))
        if not (1 <= mo <= 12 and 1 <= dd <= 31):
            continue
        if not m.group(1):
            if (mo, dd) >= (today.month, today.day):
                pass
            elif today.month >= 10 and mo <= 2:
                y += 1
            else:
                continue
        try:
            return date(y, mo, dd)
        except ValueError:
            continue
    return None



def drop_reason(item, level):
    title = item.get("title") or ""
    # 讲座类不在这里丢，交给 classify 判断是不是本院学术报告
    for kw in DROP_ANY:
        if kw in title:
            return "过滤词:" + kw
    for kw in DROP_BY_LEVEL.get(level, []):
        if kw in title:
            return "非本阶段:" + kw
    return None


def load_config():
    here = BASE_DIR
    p = os.path.join(here, "config.json")
    if not os.path.isfile(p):
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _as_int(v, default=0):
    """容忍 "2028届" / "大三" 这类写法，抽不出数字就当 0。"""
    if isinstance(v, int):
        return v
    m = re.search(r"\d{4}", str(v or ""))
    return int(m.group(0)) if m else default


def load_profile():
    """读取个人画像：校区、学院、毕业届、关注方向。"""
    prof = (load_config() or {}).get("profile") or {}
    return {
        "campus": (prof.get("campus") or "").strip(),
        "college": (prof.get("college") or "").strip(),
        "cohort": _as_int(prof.get("cohort")),
        "interests": prof.get("interests") or [],
        "title": (prof.get("title") or "").strip(),
        "housing": (prof.get("housing") or "").strip(),
        "commute": (prof.get("commute") or "").strip(),
        "grade": (prof.get("grade") or "").strip(),
    }


CAMPUS_RE = re.compile(r"([\u4e00-\u9fa5]{2})校区")


def wrong_campus(item, prof):
    """标题写的是别的校区，就跟你没关系。没写校区的通知一律保留。"""
    mine = (prof.get("campus") or "").replace("校区", "").strip()
    if not mine:
        return False
    found = set(CAMPUS_RE.findall(item.get("title") or ""))
    return bool(found) and mine not in found


def profile_drop(item, prof):
    """按个人情况直接排除不相关的东西。返回原因或 None。"""
    title = item.get("title") or ""

    if wrong_campus(item, prof):
        return "不是你的校区"

    # 毕业流程：离毕业还差两年以上就先不烦你
    if prof["cohort"] and prof["cohort"] - date.today().year >= 2:
        for kw in GRAD_FLOW:
            if kw in title:
                return "毕业流程还早(%s)" % kw

    # 就业方向：没选的就不报
    wanted = {INTEREST_TO_GROUP[i] for i in prof["interests"] if i in INTEREST_TO_GROUP}
    if wanted:
        hit = {grp for grp, kws in JOB_GROUP.items() if any(k in title for k in kws)}
        if hit and not (hit & wanted):
            return "不是你的方向(%s)" % "/".join(sorted(hit))
    return None


def is_own_college(publisher, prof):
    """publisher 是不是用户自己的学院。支持全称或去掉「学院/学部」的简称。"""
    own = (prof or {}).get("college") or ""
    if not own or not publisher:
        return False
    if own in publisher:
        return True
    short = own.replace("学院", "").replace("学部", "").strip()
    return bool(short) and len(short) >= 2 and short in publisher


def score(item, prof=None):
    title = item.get("title") or ""
    publisher = item.get("publisher") or ""
    total, why = 0, []
    for kw, w in BOOST.items():
        if kw in title:
            total += w
            why.append(kw)
    for kw, w in PENALTY.items():
        if kw in title:
            total += w
            why.append(kw)

    # 住校内：宿舍、门禁、停水停电跟自己直接相关
    prof = prof or {}
    if "校内" in (prof.get("housing") or ""):
        if any(k in title for k in ("宿舍", "住宿", "停水", "停电", "断网", "停网", "门禁")):
            total += 2
            why.append("住校内")
    # 骑车/走路：封路、施工直接改路线
    if any(k in (prof.get("commute") or "") for k in ("骑车", "走路", "步行", "单车")):
        if any(k in title for k in ("封路", "施工", "封闭", "道路")):
            total += 2
            why.append("影响通勤")

    if is_own_college(publisher, prof):
        total += 3
        why.append("本院")
    else:
        for name, w in CORE_PUBLISHERS.items():
            if name in publisher:
                total += w
                why.append("校级")
                break
        else:
            if publisher and ("学院" in publisher or "学部" in publisher):
                total -= 2

    return total, why


def classify(item, prof=None):
    """返回 (区块, 分数)。区块为 None 表示丢弃。"""
    title = item.get("title") or ""
    cat = item.get("category") or ""
    pub = item.get("publisher") or ""
    prof = prof or {}
    s, _ = score(item, prof)

    # 学术报告：只有本院的、且你勾了「学术」才报；其他讲座照旧丢
    if cat in DROP_CATEGORIES:
        if is_own_college(pub, prof) and "学术" in (prof.get("interests") or []):
            return "acad", THRESHOLD
        return None, s

    # 就业优先：只要带具体招聘/报考/手续信息，就算数
    if any(k in title for k in JOB_HARD):
        sc = s + 4
        if "讲座" in title and not any(k in title for k in JOB_HARD_ANCHOR):
            return None, s
        if sc < 0:
            return None, s
        return "job", sc

    if any(k in title for k in ENV_WORDS):
        return ("env", s) if s >= THRESHOLD - 1 else (None, s)

    if any(k in title for k in GAIN_WORDS):
        return ("gain", s) if s >= THRESHOLD - 1 else (None, s)

    if any(k in title for k in DUE_WORDS):
        return ("due", s) if s >= THRESHOLD else (None, s)

    return (None, s)


def human_note(title, sec):
    """给一条公告配一句人话：这是干嘛的、不管会怎样。"""
    best = None
    for kw, txt in HUMAN.items():
        if kw in title:
            if best is None or len(kw) > len(best[0]):
                best = (kw, txt)
    if best:
        return best[1]
    return HUMAN_BY_SECTION.get(sec, "")



SECTION_META = {
    "env": ("⚠️ 校园环境", "影响你今天的出门、用水用电"),
    "due": ("🔴 要办的事", "有截止，不办会吃亏"),
    "job": ("💼 就业", "招聘会 / 宣讲 / 选调 / 公务员 / 实习 / 手续"),
    "acad": ("🎓 学术", "本院的学术报告、讲座"),
    "gain": ("💰 机会与资助", "访学 / 交换 / 竞赛 / 奖助 / 补助"),
}
SHORT_NAME = {"env": "环境", "due": "要办", "job": "就业",
              "acad": "学术", "gain": "机会"}
ORDER = ["env", "due", "job", "acad", "gain"]


def short_title(t):
    """把「关于做好2027届毕业研究生学历证书电子图像采集工作的通知」压成
    「2027届毕业研究生学历证书电子图像采集」。标题短一半，一眼能扫。"""
    if not t:
        return ""
    s = t
    for _ in range(3):  # 前缀可能叠好几层，反复剥
        s = re.sub(r"^【[^】]{1,14}】\s*", "", s)
        s = re.sub(r"^\d{4}届[^：:]{0,14}就业工作（\d+）\s*[：:]\s*", "", s)
        s = re.sub(r"^[^｜|]{2,26}[｜|]\s*", "", s)
        s = re.sub(r"^关于(做好|开展|组织|举办|开通|印发|发布|报送|征集|推荐|参加)?", "", s)
        s = re.sub(r"^(进一步|开展|举办)", "", s)
    # 长括号一般是补充说明，删掉更清爽（短的如「（26）」保留）
    s = re.sub(r"（[^）]{8,}）", "", s)
    s = re.sub(r"\([^)]{8,}\)", "", s)
    # 学术报告：砍掉「20XX年度XX学院高水平」这种重复前缀
    s = re.sub(r"^\d{4}年度[^：:]{0,24}?(高水平)?学术报告", "学术报告", s)
    s = re.sub(r"^(\d{4}届)?[^：:]{0,24}?(高水平)?学术报告", "学术报告", s)
    s = re.sub(r"(的)?(通知|公告|公示|函|意见|说明)(（\d+）)?\s*$", "", s)
    s = re.sub(r"（\d+）\s*$", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" 　·、，,")
    return s or t


def digest(text):
    """从正文抽「什么时候」和「在哪」，用于一眼看懂。"""
    flat = _flatten(text)
    if not flat:
        return "", ""
    today = date.today()

    # 未来的日期，去重排序（支持「10月24-25日」这种区间写法）
    ds = set()
    for m_, d_ in _all_dates(flat):
        if 1 <= m_ <= 12 and 1 <= d_ <= 31 and (m_, d_) >= (today.month, today.day):
            ds.add((m_, d_))
    ds = sorted(ds)

    when = ""
    if ds:
        if len(ds) >= 2 and ds[0][0] == ds[-1][0]:
            when = "%d月%d-%d日" % (ds[0][0], ds[0][1], ds[-1][1])
        else:
            when = "%d月%d日" % ds[0]
        if re.search(r"(截止|截至|前完成|前提交|系统.*关闭)", flat):
            when += " 截止"

    where = ""
    for pat in (r"地点[:：为]?\s*([^。；，,：]{3,26})",
                r"地址[:：为]?\s*([^。；，,：]{3,26})",
                r"在([^。；，,：]{4,26}?)(?:举行|举办|召开|开展|进行)"):
        mm = re.search(pat, flat)
        if mm:
            cand = mm.group(1).strip()
            cand = re.split(r"主办|承办|协办|三、|四、|五、|活动内容|工作要求|"
                            r"宣讲对象|联系人|联系|时间|日期|报告人|主讲人", cand)[0].strip(" ·、,，")
            if 3 <= len(cand) <= 26 and not re.match(r"^[三四五六七八九十]", cand):
                where = cand
                break
    return when, where


def expired(month_day_text, today=None):
    """「10月23日」这种日期早于今天 = 已经过去了。没有日期就当没过期。"""
    if not month_day_text:
        return False
    m = re.search(r"(\d{1,2})月(\d{1,2})日", month_day_text)
    if not m:
        return False
    today = today or date.today()
    return (int(m.group(1)), int(m.group(2))) < (today.month, today.day)


# 支持「10月28日」「10月24-25日」「10月28日至11月1日」几种写法
DATE_SPAN = re.compile(r"(\d{1,2})月(\d{1,2})(?:\s*[-–—~至]\s*(\d{1,2}))?\s*日")


def _all_dates(text):
    out = []
    for m, d1, d2 in DATE_SPAN.findall(text or ""):
        out.append((int(m), int(d1)))
        if d2:
            out.append((int(m), int(d2)))
    return out


def all_dates_past(text):
    """正文里出现的日期是不是全都过去了。用来判断活动是否已结束。"""
    ds = _all_dates(_flatten(text))
    if not ds:
        return False
    t = date.today()
    return all(x < (t.month, t.day) for x in ds)


def human_note(title, sec):
    """给一条公告配一句人话：这是干嘛的、不管会怎样。
    更具体的类别（联合培养、竞赛、实习……）优先于泛化的词（宣讲会）。"""
    best_kw, best_txt = None, None
    for kw, txt in HUMAN.items():
        if kw in title:
            strong = kw in HUMAN_STRONG
            if (best_kw is None or strong > (best_kw in HUMAN_STRONG)
                    or (strong == (best_kw in HUMAN_STRONG) and len(kw) > len(best_kw))):
                best_kw, best_txt = kw, txt
    if best_txt:
        return best_txt
    return HUMAN_BY_SECTION.get(sec, "")


def days_left(when, today=None):
    """离那个日期还有几天。用来给出「还有 N 天」的紧迫感。"""
    m = re.search(r"(\d{1,2})月(\d{1,2})日", when or "")
    if not m:
        return None
    t = today or date.today()
    try:
        d = date(t.year, int(m.group(1)), int(m.group(2)))
    except ValueError:
        return None
    return (d - t).days


CONFIG_TEMPLATE = {
    "smtp": {"host": "smtp.qq.com", "port": 465, "user": "", "auth": "", "to": ""},
    "wecom_webhook": "",
    "profile": {"campus": "", "college": "", "cohort": 0, "title": "",
                "interests": [], "housing": "", "commute": "", "grade": ""},
}


def do_init():
    """首次配置：只问两件事——邮箱、授权码。其余留空即可用。"""
    path = os.path.join(BASE_DIR, "config.json")
    print("第一次使用，先配好发信邮箱。\n")
    print("QQ 邮箱授权码在：mail.qq.com → 设置 → 账号 → 开启 POP3/SMTP → 生成授权码")
    print("（是 16 位字母，不是 QQ 登录密码。用别的邮箱也行，改 config.json 里的 host）\n")

    addr = input("你的邮箱地址：").strip()
    if not addr:
        print("没填邮箱，退出。")
        return
    try:
        import getpass
        code = getpass.getpass("邮箱授权码（输入时不显示）：").strip()
    except Exception:
        code = input("邮箱授权码：").strip()
    if not code:
        print("没填授权码，退出。")
        return

    cfg = json.loads(json.dumps(CONFIG_TEMPLATE))
    cfg["smtp"].update({"user": addr, "to": addr, "auth": code})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("\n已写入 %s" % path)
    print("下一步验证：python scripts/notice_daily.py --email")
    print("想按你的情况定制，再编辑 config.json 里的 profile（校区、学院、毕业届、关注方向）。")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--range", default="24h", help="近期窗口：环境/待办只看这里")
    ap.add_argument("--wide", default="7d", help="宽窗口：就业/机会提前一周就在发")
    ap.add_argument("--level", default="pg", choices=["pg", "ug", "phd"])
    ap.add_argument("--all", action="store_true", help="调试：显示全部去留")
    ap.add_argument("--no-detail", action="store_true", help="不抓正文")
    ap.add_argument("--push", action="store_true", help="生成后推送到企业微信群机器人")
    ap.add_argument("--webhook", default=None, help="临时指定企微 webhook 地址")
    ap.add_argument("--html", default=None, help="另存一份 HTML（给邮件用），传目录或文件路径")
    ap.add_argument("--email", action="store_true", help="生成后按 config.json 的 SMTP 配置发到邮箱")
    ap.add_argument("--skip-if-sent", action="store_true",
                    help="今天已经成功发过就跳过（配合多个时间点的兜底任务）")
    ap.add_argument("--done", default=None, help="把某条待办标记为已完成（传公告 id 或标题片段）")
    ap.add_argument("--init", action="store_true", help="首次配置：填写邮箱和授权码，生成 config.json")
    args = ap.parse_args()

    if args.init:
        do_init()
        return

    # 手动销账：--done 585526
    if args.done:
        pend = load_pending()
        hit = [k for k, v in pend.items()
               if args.done in k or args.done in (v.get("title") or "")]
        if not hit:
            print("待办里没找到「%s」。当前的待办：" % args.done)
            for k, v in sorted(pend.items(), key=lambda x: x[1].get("due", "")):
                print("  %s  %s  %s" % (k, v.get("due"), v.get("title")))
            return
        for k in hit:
            pend.pop(k)
        save_pending(pend)
        print("已销账 %d 条。" % len(hit))
        return

    if args.skip_if_sent and _already_sent(date.today()):
        print("今天已经发送过，跳过。")
        return

    prof = load_profile()

    # 两个时间窗：短期看环境待办，长期看就业机会（招聘会提前一周发）
    try:
        recent = run_cli(["notice", "search", "--range", args.range, "--limit", "100"]).get("items", [])
        wide = run_cli(["notice", "search", "--range", args.wide, "--limit", "100"]).get("items", [])
    except SystemExit as e:
        # 抓取失败也要让你知道，不能让日报悄悄消失
        if args.email and not os.path.isfile(_alert_marker(date.today())):
            cfg = load_smtp()
            if cfg:
                send_alert(str(e) or "未知错误", cfg)
                print("\n[已发失败告警邮件]")
        raise

    recent_ids = {it.get("id") for it in recent}
    merged, seen = [], set()
    for it in recent + wide:
        i = it.get("id")
        if i in seen:
            continue
        seen.add(i)
        merged.append(it)

    buckets = {k: [] for k in ORDER}
    dropped = []

    for it in merged:
        r = drop_reason(it, args.level) or profile_drop(it, prof)
        if r:
            dropped.append((it, r))
            continue
        sec, s = classify(it, prof)
        if not sec:
            dropped.append((it, "不够重要(%d)" % s))
            continue
        buckets[sec].append((it, s))

    # 环境类：只要「事件还没结束」就留着，不管公告是哪天发的。
    # 封路、停水这类往往提前好几天发，只看 24 小时会漏掉。
    if not args.no_detail:
        for it, s in list(buckets["env"]):
            text = safe_view(it.get("id"))
            if all_dates_past(text):
                buckets["env"].remove((it, s))
                dropped.append((it, "通知里的日期都已过去"))
        for it, s in list(buckets["job"]):
            if all_dates_past(safe_view(it.get("id"))):
                buckets["job"].remove((it, s))
                dropped.append((it, "活动已结束"))

    for k in buckets:
        buckets[k].sort(key=lambda x: -x[1])

    kept_n = sum(len(v) for v in buckets.values())

    if args.all:
        print("=== 近期 %d 条 / 宽窗口 %d 条，去重后 %d 条，留下 %d 条 ==="
              % (len(recent), len(wide), len(merged), kept_n))
        for k in ORDER:
            print("-- %s (%d) --" % (SECTION_META[k][0], len(buckets[k])))
            for it, s in buckets[k]:
                print("   [%2d] %s | %s" % (s, it.get("publisher") or "",
                                            (it.get("title") or "")[:62]))
        print("-- 丢弃 %d 条，抽样 --" % len(dropped))
        for it, r in dropped[:18]:
            print("   (%s) %s" % (r, (it.get("title") or "")[:56]))
        print()

    # ---------------------------------------------------------- 抽成结构化条目
    rows = {k: [] for k in ORDER}
    for k in ORDER:
        for it, s in buckets[k][:CAP[k]]:
            text = "" if args.no_detail else safe_view(it.get("id"))
            when, where = digest(text)
            note = "" if args.no_detail else key_point(text)
            raw_title = it.get("title") or ""
            atts = view_atts(it.get("id")) if not args.no_detail else []
            fields = extract_fields(text, atts) if not args.no_detail else []
            att_lines = []
            if atts and k in ("due", "job", "gain") and not args.no_detail:
                att_lines = attachment_digest(it.get("id"), atts)
            due = infer_due(dict(fields).get("截止", ""), when, note)
            rows[k].append({
                "id": str(it.get("id") or ""),
                "title": short_title(raw_title),
                "when": when, "where": where, "note": note[:58],
                "human": human_note(raw_title, k),
                "left": days_left(when),
                "fields": fields[:FIELD_LIMIT.get(k, 3)],
                "att_lines": att_lines,
                "due": due,
                "url": it.get("url") or "",
                "date": it.get("date") or "",
                "publisher": it.get("publisher") or "",
            })

    stats = {"recent": len(recent), "wide": len(wide),
             "merged": len(merged), "kept": kept_n, "dropped": len(dropped)}

    # ---------------------------------------------------------- 待办清单
    today_d = date.today()
    old_pend = load_pending()
    pend = dict(old_pend)
    for k in list(pend):                      # 过期的自动清掉
        if (pend[k].get("due") or "") < today_d.isoformat():
            pend.pop(k)
    for k in ORDER:
        for r in rows[k]:
            rid = r.get("id")
            if r.get("due") and k in ("due", "job", "gain"):
                if rid and rid not in pend:
                    pend[rid] = {"title": r["title"],
                                 "due": r["due"].isoformat(),
                                 "url": r["url"], "sec": k}
                r["is_new"] = rid not in old_pend
            else:
                r["is_new"] = True
    save_pending(pend)
    stats["pending"] = len(pend)

    today = date.today()
    wd = "一二三四五六日"[today.weekday()]

    text = render_text(rows, today, wd, stats, args, pend)
    print(text)

    html_path = None
    if args.html or args.email:
        _prune_reports()
        if not args.html:
            d = os.path.join(BASE_DIR, "reports")
            os.makedirs(d, exist_ok=True)
            args.html = d
        html_path = make_html(rows, today, wd, stats, args, pend)
        print("\n[HTML] %s" % html_path)

    if args.email and html_path:
        _do_email(html_path, today, wd, args)

    if args.push:
        _do_push(text, args)


def _counts(rows):
    return {k: len(v) for k, v in rows.items()}


def verdict(rows, pend):
    """一句话裁决：今天到底要不要管。这是整份日报最该先看到的东西。"""
    today = date.today()
    new_n = sum(1 for k in ORDER for r in rows[k] if r.get("is_new", True))
    if pend:
        first_id = sorted(pend, key=lambda k: pend[k].get("due") or "9999")[0]
        v = pend[first_id]
        try:
            d = date.fromisoformat(v.get("due") or "")
            left = (d - today).days
        except Exception:
            left = None
        tag = ""
        if left is not None:
            tag = "今天截止" if left == 0 else "还有 %d 天" % left
        name = v["title"]
        if len(name) > 22:
            name = name[:20] + "…"
        extra = "，今天新增 %d 条" % new_n if new_n else ""
        return "在办 %d 件。最近的是「%s」%s%s。" % (len(pend), name,
                                                    ("，" + tag) if tag else "", extra)

    flat = [(k, r) for k in ORDER for r in rows[k]]
    if not flat:
        return "今天没有需要你处理的事。"

    def urgency(pair):
        left = pair[1].get("left")
        return 99 if left is None else left

    flat.sort(key=urgency)
    k, top = flat[0]
    when = top.get("when") or ""
    left = top.get("left")
    tail = ""
    if left is not None:
        tail = "今天" if left == 0 else ("还有 %d 天" % left if left > 0 else "已过期")
    name = top["title"]
    if len(name) > 24:
        name = name[:22] + "…"
    tip = "最急的是「%s」%s%s" % (
        name,
        ("，" + when) if (when and left != 0) else "",
        ("，" + tail) if tail else "")
    return "今天 %d 件。%s。" % (len(flat), tip)


def render_text(rows, today, wd, stats, args, pend=None):
    """聊天/终端版：短标题 + 一行时间地点 + 链接。"""
    out = []
    say = out.append
    pend = pend or {}
    c = _counts(rows)
    head = " · ".join("%s %d" % (SHORT_NAME[k], c[k]) for k in ORDER if c[k])

    say("# 公文通日报 %d月%d日 周%s" % (today.month, today.day, wd))
    say("")
    if not head and not pend:
        say("今天没有需要你处理的事。")
        say("")
        say("（近 %s 的 %d 条 + 一周内 %d 条，共 %d 条，全部判为无关或已过期）"
            % (args.range, stats["recent"], stats["wide"], stats["merged"]))
        return "\n".join(out)

    say("**%s**" % verdict(rows, pend or {}))
    say("")
    if head:
        say("%s" % head)
        say("")

    # ---------------------------------------------------------- 在办清单
    if pend:
        say("## ⏳ 在办（%d 件）" % len(pend))
        for k in sorted(pend, key=lambda x: pend[x].get("due") or "9999"):
            v = pend[k]
            try:
                d = date.fromisoformat(v.get("due") or "")
                left = (d - today).days
                tag = "今天截止" if left == 0 else "还有 %d 天" % left
            except Exception:
                left, tag = None, ""
            mark = "⏰ " if left is not None and left <= 3 else "· "
            say("%s**%s**" % (mark, v["title"]))
            say("   %s · %s" % (v.get("due") or "", tag) if tag else "   %s" % v.get("due") or "")
        say("   做完了就销账：python scripts/notice_daily.py --done <编号>")
        say("")

    for k in ORDER:
        items = [r for r in rows[k] if r.get("is_new", True)]
        if not items:
            continue
        say("## %s" % SECTION_META[k][0])
        for i, r in enumerate(items, 1):
            bullet = "%d." % i if k == "due" else "·"
            say("%s **%s**" % (bullet, r["title"]))
            bits = [x for x in (r["when"], r["where"]) if x]
            fs = list(r.get("fields") or [])
            labels = {lb for lb, _ in fs}
            # 字段里已有更精确的时间地点，顶部不再重复；倒计时并入「时间」那一行
            if labels & {"时间", "地点"}:
                bits = []
                n = r.get("left")
                if n is not None:
                    tag = "今天结束" if n == 0 else ("还有 %d 天" % n if n > 0 else "已过期")
                    fs = [(lb, v + "（%s）" % tag) if lb == "时间" else (lb, v)
                          for lb, v in fs]
                    if "时间" not in labels:
                        fs.insert(0, ("倒计时", tag))
            elif r.get("left") is not None:
                n = r["left"]
                bits.append("今天" if n == 0 else ("还有 %d 天" % n if n > 0 else "已过期"))
            if not bits and not fs and r["note"]:
                bits = [r["note"]]
            if bits and any(bits):
                say("   %s" % " · ".join([b for b in bits if b]))
            for label, val in fs:
                say("   %s：%s" % (label, val))
            if r.get("att_lines"):
                say("   附件里写的：")
                for line in r["att_lines"][:4]:
                    say("     %s" % line)
            if r.get("human"):
                say("   %s" % r["human"])
            if r["url"] and k in ("due", "gain"):
                say("   原文（需登录）：%s" % r["url"])
        say("")

    return "\n".join(out)


CSS = """
body{margin:0;padding:0;background:#f5f6f7;}
.wrap{max-width:600px;margin:0 auto;padding:18px 16px 28px;background:#ffffff;
 font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;
 color:#1f2328;font-size:15px;line-height:1.6;}
.h1{font-size:21px;font-weight:700;margin:0 0 4px;}
.sub{color:#8a9099;font-size:13px;margin:0 0 14px;}
.chips{margin:0 0 18px;}
.chip{display:inline-block;padding:3px 9px;margin:0 6px 6px 0;border-radius:11px;
 font-size:12px;font-weight:600;background:#f0f2f5;color:#4a5158;}
.sec{font-size:14px;font-weight:700;margin:18px 0 8px;padding-left:9px;
 border-left:3px solid #4a5158;color:#1f2328;}
.item{padding:10px 0 10px 12px;border-bottom:1px solid #eef0f2;}
.item:last-child{border-bottom:none;}
.t{font-weight:600;font-size:15px;margin:0 0 3px;}
.m{color:#6b7280;font-size:13px;margin:0 0 3px;}
.n{color:#4a5158;font-size:13px;margin:0 0 4px;}
.a{color:#1a6ee0;font-size:12.5px;text-decoration:none;}
.foot{margin-top:22px;padding-top:12px;border-top:1px solid #eef0f2;
 color:#9aa1a9;font-size:12px;line-height:1.7;}
"""

SEC_COLOR = {"env": "#d97706", "due": "#dc2626", "job": "#0f766e",
             "acad": "#2563eb", "gain": "#7c3aed"}

# 邮件客户端（尤其 QQ 邮箱）常把 <style> 丢掉，关键样式一律写进 style 属性
S_WRAP = ("max-width:600px;margin:0 auto;padding:18px 16px 28px;background:#ffffff;"
          "font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;"
          "color:#1f2328;font-size:15px;line-height:1.6;")
S_H1 = "font-size:21px;font-weight:700;margin:0 0 4px;color:#1f2328;"
S_SUB = "color:#8a9099;font-size:13px;margin:0 0 14px;"
S_CHIP = ("display:inline-block;padding:3px 9px;margin:0 6px 6px 0;border-radius:11px;"
          "font-size:12px;font-weight:600;background:#f0f2f5;color:#4a5158;")
S_SEC = ("font-size:14px;font-weight:700;margin:18px 0 8px;padding-left:9px;"
         "border-left:3px solid #4a5158;color:#1f2328;")
S_ITEM = "padding:10px 0 10px 12px;border-bottom:1px solid #eef0f2;"
S_T = "font-weight:600;font-size:15px;margin:0 0 3px;color:#1f2328;"
S_M = "color:#6b7280;font-size:13px;margin:0 0 3px;"
S_N = "color:#4a5158;font-size:13px;margin:0 0 4px;"
S_H = "color:#3f4650;font-size:13.5px;margin:3px 0 4px;line-height:1.65;"
S_V = ("background:#f6f8fa;border-left:3px solid #1f2328;padding:10px 12px;"
       "font-size:14.5px;font-weight:600;color:#1f2328;margin:0 0 18px;"
       "line-height:1.6;border-radius:0 4px 4px 0;")
S_A = "color:#1a6ee0;font-size:12.5px;text-decoration:none;"
S_F = ("background:#fafbfc;border:1px solid #eef0f2;border-radius:4px;"
       "padding:6px 8px;margin:4px 0 2px;")
S_FL = "color:#8a9099;font-size:12px;display:inline-block;min-width:58px;"
S_FV = "color:#2b3138;font-size:12.5px;"
S_FOOT = ("margin-top:22px;padding-top:12px;border-top:1px solid #eef0f2;"
          "color:#9aa1a9;font-size:12px;line-height:1.7;")


def _prune_reports(days=40):
    """报告留最近 40 天，别把磁盘塞满。"""
    d = os.path.join(BASE_DIR, "reports")
    if not os.path.isdir(d):
        return
    cut = today_ts = date.today().toordinal() - days
    for name in os.listdir(d):
        m = re.search(r"(\d{4}-\d{2}-\d{2})", name)
        if not m:
            continue
        try:
            if date.fromisoformat(m.group(1)).toordinal() < cut:
                os.remove(os.path.join(d, name))
        except Exception:
            pass


def make_html(rows, today, wd, stats, args, pend=None):
    """邮件版：只用内联样式 + 简单标签，QQ 邮箱能正常渲染。"""
    c = _counts(rows)
    html = ['<div style="%s">' % S_WRAP]
    html.append('<div style="%s">公文通日报</div>' % S_H1)
    html.append('<div style="%s">%d月%d日 周%s · 只报大事</div>'
                % (S_SUB, today.month, today.day, wd))

    chips = "".join('<span style="%s">%s %d</span>' % (S_CHIP, SHORT_NAME[k], c[k])
                    for k in ORDER if c[k])
    pend = pend or {}
    if not chips and not pend:
        html.append('<div style="margin:0 0 18px"><span style="%s">今天无事</span></div>' % S_CHIP)
        html.append('<div style="%s">近 %s 的 %d 条 + 一周内 %d 条，全部判为无关或已过期。</div>'
                    % (S_FOOT, args.range, stats["recent"], stats["wide"]))
        html.append("</div>")
        return _write_html("\n".join(html), today, args)

    if chips:
        html.append('<div style="margin:0 0 18px">%s</div>' % chips)

    html.append('<div style="%s">%s</div>' % (S_V, _esc(verdict(rows, pend))))

    # 在办清单
    if pend:
        html.append('<div style="%s border-left-color:#0f766e">⏳ 在办（%d 件）</div>'
                    % (S_SEC, len(pend)))
        html.append('<div style="%s">' % S_F)
        for k in sorted(pend, key=lambda x: pend[x].get("due") or "9999"):
            v = pend[k]
            try:
                d = date.fromisoformat(v.get("due") or "")
                left = (d - today).days
                tag = "今天截止" if left == 0 else "还有 %d 天" % left
            except Exception:
                tag = ""
            warn = "⏰ " if tag and "0 天" not in tag and left <= 3 else ""
            html.append('<div style="margin:3px 0;font-size:13px">'
                        '<b>%s%s</b><span style="color:#6b7280"> · %s %s</span></div>'
                        % (warn, _esc(v["title"]), _esc(v.get("due") or ""), _esc(tag)))
        html.append("</div>")

    for k in ORDER:
        items = [r for r in rows[k] if r.get("is_new", True)]
        if not items:
            continue
        html.append('<div style="%s border-left-color:%s">%s</div>'
                    % (S_SEC, SEC_COLOR[k], SECTION_META[k][0]))
        for r in items:
            html.append('<div style="%s">' % S_ITEM)
            html.append('<div style="%s">%s</div>' % (S_T, _esc(r["title"])))
            bits = [x for x in (r["when"], r["where"]) if x]
            if r.get("left") is not None:
                n = r["left"]
                bits.append("今天" if n == 0 else ("还有 %d 天" % n if n > 0 else "已过期"))
            if bits:
                html.append('<div style="%s">%s</div>' % (S_M, _esc(" · ".join(bits))))
            elif r["note"]:
                html.append('<div style="%s">%s</div>' % (S_N, _esc(r["note"])))

            fs = r.get("fields") or []
            if fs:
                html.append('<div style="%s">' % S_F)
                for label, val in fs:
                    html.append('<div style="margin:1px 0"><span style="%s">%s</span>'
                                '<span style="%s">%s</span></div>'
                                % (S_FL, _esc(label), S_FV, _esc(val)))
                html.append("</div>")

            if r.get("att_lines"):
                html.append('<div style="%s">' % S_F)
                html.append('<div style="%s">附件里写的：</div>' % S_FL)
                for line in r["att_lines"][:4]:
                    html.append('<div style="%s">%s</div>' % (S_FV, _esc(line)))
                html.append("</div>")

            if r.get("human"):
                html.append('<div style="%s">%s</div>' % (S_H, _esc(r["human"])))
            if r["url"] and k in ("due", "gain"):
                html.append('<div style="margin-top:4px"><a href="%s" style="%s">原文（需登录）→</a></div>'
                            % (_esc(r["url"]), S_A))
            html.append("</div>")

    html.append('<div style="%s">近 %s 扫 %d 条 + 一周内 %d 条，共 %d 条，'
                '留下 %d 条，过滤 %d 条（答辩公告 / 新闻稿 / 讲座 / 名单公示等）。</div>'
                % (S_FOOT, args.range, stats["recent"], stats["wide"], stats["merged"],
                   stats["kept"], stats["dropped"]))
    html.append("</div>")
    return _write_html("\n".join(html), today, args)


def _esc(s):
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _write_html(body, today, args):
    doc = ("<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
           "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
           "<title>公文通日报 %s</title><style>%s</style></head><body>%s</body></html>"
           % (today.isoformat(), CSS, body))
    target = args.html
    if os.path.isdir(target):
        target = os.path.join(target, "report-%s.html" % today.isoformat())
    with open(target, "w", encoding="utf-8") as f:
        f.write(doc)
    return os.path.abspath(target)


def load_smtp():
    """从 config.json 读 SMTP 配置（自己发信，不依赖 Agent 邮箱）。"""
    here = BASE_DIR
    p = os.path.join(here, "config.json")
    if not os.path.isfile(p):
        return None
    try:
        with open(p, encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return None
    s = cfg.get("smtp") or {}
    if not (s.get("user") and s.get("auth")):
        return None
    return {
        "host": s.get("host") or "smtp.qq.com",
        "port": int(s.get("port") or 465),
        "user": s["user"],
        "auth": s["auth"],
        "to": s.get("to") or s["user"],
    }


def send_mail(html_path, subject, cfg):
    """用 SMTP 直接把 HTML 日报发出去。"""
    import smtplib
    import ssl
    from email.message import EmailMessage
    from email.utils import formataddr

    with open(html_path, encoding="utf-8") as f:
        html = f.read()

    msg = EmailMessage()
    msg["From"] = formataddr(("公文通日报", cfg["user"]))
    msg["To"] = cfg["to"]
    msg["Subject"] = subject
    msg.set_content("这是一封 HTML 日报，请在支持 HTML 的客户端里查看。")
    msg.add_alternative(html, subtype="html")

    try:
        ctx = ssl.create_default_context()
        if cfg["port"] == 465:
            with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=40, context=ctx) as s:
                s.login(cfg["user"], cfg["auth"])
                s.send_message(msg)
        else:
            with smtplib.SMTP(cfg["host"], cfg["port"], timeout=40) as s:
                s.starttls(context=ctx)
                s.login(cfg["user"], cfg["auth"])
                s.send_message(msg)
    except Exception as e:
        return False, "%s: %s" % (type(e).__name__, e)
    return True, "已发送到 %s" % cfg["to"]


def _mark_sent(today):
    d = os.path.join(BASE_DIR, "reports")
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, ".sent-%s" % today.isoformat()), "w").close()


def _already_sent(today):
    d = os.path.join(BASE_DIR, "reports")
    return os.path.isfile(os.path.join(d, ".sent-%s" % today.isoformat()))


def _alert_marker(today):
    d = os.path.join(BASE_DIR, "reports")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, ".alert-%s" % today.isoformat())


def send_alert(reason, cfg):
    """抓取失败时发一封告警，别让日报悄悄消失。"""
    import smtplib
    import ssl
    from email.message import EmailMessage
    from email.utils import formataddr

    hint = reason
    if any(k in reason for k in ("LOGIN_REQUIRED", "403", "PERMISSION")):
        hint += ("\n\n大概率是深大登录态过期了。在电脑上执行一次：\n"
                 "    szu-cli auth login\n然后在弹出的浏览器里重新登录即可。")
    html = ("<div style='font-family:-apple-system,sans-serif;font-size:15px;"
            "line-height:1.7;color:#1f2328;max-width:560px'>"
            "<div style='font-size:18px;font-weight:700;margin-bottom:10px'>"
            "今天的公文通日报没生成成功</div>"
            "<div style='background:#fff5f5;border-left:3px solid #dc2626;"
            "padding:10px 12px;margin:0 0 14px;font-size:13.5px;white-space:pre-wrap'>"
            + _esc(hint) + "</div>"
            "<div style='color:#6b7280;font-size:13px'>这条消息是自动发的。"
            "修好之后下一次会自动恢复正常，不用再配置。</div></div>")

    msg = EmailMessage()
    msg["From"] = formataddr(("公文通日报", cfg["user"]))
    msg["To"] = cfg["to"]
    msg["Subject"] = "【公文通日报】今天没生成成功"
    msg.set_content("今天的日报没生成成功：\n" + reason)
    msg.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=40,
                              context=ssl.create_default_context()) as s:
            s.login(cfg["user"], cfg["auth"])
            s.send_message(msg)
        open(_alert_marker(date.today()), "w").close()
        return True
    except Exception:
        return False


def _do_email(html_path, today, wd, args):
    cfg = load_smtp()
    if not cfg:
        print("\n[邮件跳过] 没找到 SMTP 配置。在 szu-daily/config.json 里写：\n"
              '{\n  "smtp": {\n    "host": "smtp.qq.com",\n    "port": 465,\n'
              '    "user": "you@example.com",\n    "auth": "你的邮箱授权码",\n'
              '    "to": "you@example.com"\n  }\n}')
        return
    subject = "公文通日报 %d月%d日 周%s" % (today.month, today.day, wd)
    ok, msg = send_mail(html_path, subject, cfg)
    if ok:
        _mark_sent(today)
    print("\n[邮件] %s" % (("成功：" + msg) if ok else ("失败：" + msg)))


def _do_push(text, args):
    hook = args.webhook or load_webhook()
    if not hook:
        print("\n[推送跳过] 没有配置企业微信 webhook："
              "设置环境变量 WECOM_WEBHOOK，或在同目录 config.json 里写 "
              '{"wecom_webhook": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=..."}')
        return
    ok, msg = push_wecom(text, hook)
    print("\n[推送] %s" % ("成功：" + msg if ok else "失败：" + msg))


if __name__ == "__main__":
    main()

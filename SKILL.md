---
name: szu-notice-daily
display_name: 深大公文通日报
display_name_en: SZU Notice Daily Digest
description: 把深圳大学公文通里跟你有关的事筛出来，每天发一封中文邮件，不用点链接也能看清时间、地点、截止和要交的材料。依赖 szu-cli 的登录态抓取，只在本机运行。用户只需填写一次邮箱授权码即可收到日报。
description_zh: 自动读取深圳大学公文通，过滤答辩公告、新闻稿、无关讲座等噪音，只保留会影响你的通知，每天早上发到邮箱。每条自带时间、地点、截止、材料清单和人话解释，不用点链接登录也能看懂。
description_en: Reads Shenzhen University bulletin notices daily, filters out noise, and emails only the items that matter, with time, place, deadline, required materials, and a plain-language explanation included in the email itself.
version: 1.0.0
author: szu-notice-daily contributors
license: MIT
metadata:
  requires_cli: "szu-cli>=0.2.3"
  requires: "Python 3.8+; 无第三方依赖"
  runtime: local
---

# 深大公文通日报

把公文通里"跟你有关、需要你动手"的事挑出来，每天早上发一封邮件到你的邮箱。

**核心原则：邮件本身就是信息，不是索引。** 每条都写清楚时间、地点、谁能参加、什么时候截止、要交什么材料、找谁问——因为公文通的原文链接点进去要重新登录学号密码，那个动作本身就是失败的体验。

## 一、首次配置（只做一次）

```bash
# 0. 装数据来源 szu-cli（需要 Node.js 20+）
node --version                 # 低于 20 请先升级
npm install -g szu-cli

# 1. 确认已安装并登录
szu-cli doctor
szu-cli auth status        # 如果未登录：szu-cli auth login

# 2. 填邮箱和授权码，生成 config.json
python scripts/notice_daily.py --init

# 3. 验证能收到邮件
python scripts/notice_daily.py --email
```

`--init` 只问两件事：邮箱地址、邮箱授权码。QQ 邮箱的授权码在
`mail.qq.com → 设置 → 账号 → 开启 POP3/SMTP → 生成授权码`（16 位字母，不是登录密码）。

用其他邮箱也可以：编辑 `config.json` 里的 `smtp.host` / `smtp.port`
（网易 `smtp.163.com:465`，Gmail `smtp.gmail.com:587`）。

## 二、按你的情况定制（可选，但强烈建议）

打开 `config.json` 的 `profile` 段，留空表示不做任何过滤：

```json
"profile": {
  "campus": "粤海",
  "college": "计算机与软件学院",
  "cohort": 2028,
  "interests": ["校招", "实习", "学术"],
  "housing": "校内宿舍",
  "commute": "骑车",
  "grade": "大三"
}
```

各字段作用：

| 字段 | 作用 | 留空时 |
|---|---|---|
| `campus` | 别的校区的停水停电、封路不报 | 都报 |
| `college` | 本院通知加权；本院讲座才进「学术」 | 不区分学院 |
| `cohort` | 毕业届。离毕业两年以上时，图像采集/盲审/三方协议不报 | 不过滤毕业流程 |
| `interests` | 只报勾选的方向：`校招` `实习` `考公` `深造` `学术` | 全都收 |
| `housing` | 含「校内」→ 宿舍、停水停电、门禁加权 | 不加权 |
| `commute` | 含「骑车」「走路」→ 封路、施工加权 | 不加权 |
| `grade` | 仅作记录，不参与过滤 | — |

⚠️ `config.json` 是标准 JSON，**不能写注释**。写成 `//` 会让整个配置静默失效。

## 三、日常使用

```bash
python scripts/notice_daily.py                  # 看今天的日报（终端）
python scripts/notice_daily.py --email          # 生成并发到邮箱
python scripts/notice_daily.py --done 581110    # 待办做完了，销账
python scripts/notice_daily.py --all            # 调试：看每条为什么被留/被丢
python scripts/notice_daily.py --range 7d       # 放宽近期窗口
python scripts/notice_daily.py --no-detail      # 不抓正文，快很多
```

## 四、怎么让它每天自动跑

本方案**只在本地运行**（公文通需要登录态，云端沙箱拿不到）。所以定时任务依赖你的电脑开机。

**Windows**（支持关机后开机补跑，推荐）：

```powershell
$py = (Get-Command python).Source
$script = "绝对路径\scripts\notice_daily.py"
$action = New-ScheduledTaskAction -Execute $py -Argument "`"$script`" --email --skip-if-sent"
$trigger = New-ScheduledTaskTrigger -Daily -At "08:40"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName "SZU-Notice-Daily" -Action $action -Trigger $trigger -Settings $settings
```

`-StartWhenAvailable` 是关键：8:40 没开机，开机后会自动补跑。

**macOS / Linux**：

```bash
crontab -e
40 8 * * * cd /绝对路径 && python3 scripts/notice_daily.py --email --skip-if-sent
```

`--skip-if-sent` 让一天只发一封，重复触发也不会轰炸你。

## 五、它做什么、不做什么

**做：**
- 抓公文通，按四类归档：⚠️ 校园环境 / 🔴 要办的事 / 💼 就业 / 🎓 学术 / 💰 机会与资助
- 砍掉答辩公告、新闻稿（"成功举办""顺利举行"）、无关讲座、名单公示、教师事务
- 每条附一句人话：「这是什么 + 不管会怎样」
- 有截止日的进待办清单，每天倒数，过期自动清
- 附件（docx/xlsx/pptx）自动抽文字，把名额、条件、材料挑出来贴进邮件
- 抓取失败时发告警邮件，不会让你以为"今天没事"

**不做：**
- 不改动学校系统任何数据（纯只读）
- 不保存密码、Cookie、浏览器 profile
- 不上传任何数据到第三方服务器（邮件直连你自己的发信服务器）
- 不批量下载附件（每次最多 4 篇）

## 六、隐私

- 配置文件 `config.json` 只存在你本机，已加入 `.gitignore`
- 授权码明文保存在 `config.json`。介意的话改用邮箱的专用应用密码，或随时在邮箱后台重置
- 报告和缓存（`reports/`、`atm_cache/`、`pending.json`）同样本地保存、不进版本库

## 七、出问题时

| 现象 | 原因 | 处理 |
|---|---|---|
| 没收到邮件 | 授权码错 / 进垃圾箱 | 跑一次 `--email` 看报错；把发件人加白名单 |
| 报 `LOGIN_REQUIRED` / 403 | 深大登录态过期 | `szu-cli auth login` 重新登录 |
| 报 `PAGE_CHANGED` | 学校页面改版，适配失效 | 到 szu-cli 仓库提 issue，附上错误码 |
| 收到"没生成成功"邮件 | 同上，告警已触发 | 按邮件里的提示修 |
| 某类别总是不报 | 画像过滤太严 | `--all` 看丢弃原因，改 `profile` |

## 八、依赖与边界

- 数据来源是 [szu-cli](https://github.com/AwesomeHou/szu-cli)，本项目只做筛选、排版和发信
- szu-cli 是深大学生自制的非官方工具，学校页面改版时可能失效
- 本项目同样非官方，与深圳大学无关

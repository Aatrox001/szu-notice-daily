# 深大公文通日报

每天早上把公文通里**真正跟你有关**的事发到你邮箱。信息直接写在邮件里，不用为了看摘要去点链接、重新登录学号密码。

---

## 为什么做这个

深大公文通每天几十条：学位论文答辩公告、某某讲座成功举办、某学院访企拓岗……
真正需要你动手的可能只有一条。等你在几十条里翻出来，往往已经过了截止日期。

这个工具的立场很明确：**只报你会后悔没看到的事。**

```
公文通日报 10月26日 周一

在办 3 件。最近的是「3+1+1 联合培养宣讲会」，还有 1 天，今天新增 10 条。

## ⏳ 在办（3 件）
⏰ 深圳大学与新加坡国立大学"3+1+1"联合培养项目宣讲会
   2026-10-27 · 还有 1 天
·  研究生科研合作类海外访学资助
   2026-11-06 · 还有 11 天

## 💼 就业
· 组织统战部学生助理岗位招聘
   时间：招满为止
   地点：粤海校区 XX 楼
   谁能参加：全校招聘学生助理若干名
   校内勤工助学的岗位。时间灵活、离得近，还能认识老师。
```

注意每一条都自带信息：时间、地点、谁能参加、截止、材料、找谁问。
**你不需要点任何链接就能判断要不要去。**

---

## 三步开始

### 1️⃣ 准备数据来源

本项目依赖 [szu-cli](https://github.com/AwesomeHou/szu-cli) 抓取公文通（它负责登录态）。

```bash
node --version            # 需要 Node 20+
npm install -g szu-cli    # 安装数据来源
szu-cli doctor
szu-cli auth status     # 未登录就执行 szu-cli auth login
```

### 2️⃣ 填一次邮箱

```bash
python scripts/notice_daily.py --init
```

只问两件事：**邮箱地址** 和 **授权码**。

QQ 邮箱授权码位置：`mail.qq.com` → 设置 → 账号 → 开启「POP3/SMTP 服务」→ 生成授权码
（16 位字母，**不是** QQ 登录密码）

### 3️⃣ 验证

```bash
python scripts/notice_daily.py --email
```

收到邮件就通了。之后交给定时任务。

---

## 每天自动跑

Windows（**推荐，支持关机后开机补跑**）：

```powershell
$py = (Get-Command python).Source
$script = "D:\你的路径\szu-notice-daily\scripts\notice_daily.py"
$action  = New-ScheduledTaskAction -Execute $py -Argument "`"$script`" --email --skip-if-sent"
$trigger = New-ScheduledTaskTrigger -Daily -At "08:40"
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName "SZU-Notice-Daily" -Action $action -Trigger $trigger -Settings $settings
```

macOS / Linux：

```bash
crontab -e
# 注意带 PATH：cron 默认找不到 npm 装的可执行文件
40 8 * * * cd /你的路径/szu-notice-daily && PATH=/usr/local/bin:/usr/bin:/bin python3 scripts/notice_daily.py --email --skip-if-sent
```

> `-StartWhenAvailable` / 开机补跑很重要：桌面端的定时任务**错过时间不会补**，
> 这个参数让它在开机后立刻补发当天缺的那封。

---

## 定制成你自己的

编辑 `config.json` 的 `profile`：

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

全部留空也能用（不过滤任何东西）。填了之后：

- **campus** → 别的校区的停水停电、封路不报给你
- **college** → 本院通知加权；本院讲座才进「学术」区块
- **cohort** → 离毕业还差两年以上时，图像采集、盲审、三方协议这类流程不烦你
- **interests** → 没勾的方向整组不报（比如不考公，就收不到选调公务员）
- **housing / commute** → 住校内则宿舍和停水停电加权；骑车走路则封路施工加权

---

## 它凭什么判断"重要"

四道闸门，全过才进正文（完整标准见 **[STYLE.md](STYLE.md)**）：

**1. 受众闸** —— 是不是给你这个身份的人看的
按学段、校区、学院、届别过滤。本科生专属的评奖细则不会发给研究生。

**2. 行动闸** —— 读完会不会产生动作
报名、避让、交材料、去听。只是"知道一下"的（荣誉播报、结果公示、活动回顾）一律不进。

**3. 时效闸** —— 现在不做会不会有损失
有硬截止、有名额、不可补交的优先。

**4. 增量闸** —— 这个信息是否已被别的条目覆盖
同一项目的多场次、多条公告合并成一条，不刷数量。

**分流到五个桶，各有标准**

| 区块 | 标准 | 容量 |
|---|---|---|
| ⚠️ 校园环境 | 影响今天出门、用水用电 | 4 |
| 🔴 要办的事 | 有硬截止，不办会吃亏 | 6 |
| 💼 就业 | 有具体单位、岗位、时间地点 | 7 |
| 🎓 学术 | 本院组织的学术报告 | 3 |
| 💰 机会与资助 | 访学、交换、竞赛、奖助 | 4 |

**分数过线**：关键词加权 + 校级部门加分 + 学院级减分，低于阈值不进正文。

**宁可当天报"无事"，也不拿无关通知凑数。**
空区块整块省略——"今天没事"本身就是有用信息。

---

## 两个不那么显然的设计

**时效性看"事件有没有结束"，不看"公告哪天发的"**
封路通知常提前一周发布。按发布时间筛会漏掉，按事件结束时间筛才留得住。

**有截止的事进待办清单，每天倒数**
公文通搜索窗口只有七天，超过就查不到了。待办清单（`pending.json`）把它接住，
过期自动清，做完了 `python scripts/notice_daily.py --done <id>` 销账。

---

## 隐私

- 只读，不改动学校系统任何数据
- 不保存密码、Cookie、浏览器 profile（登录态由 szu-cli 自己管理，本项目不读取）
- 不经过任何第三方服务器，邮件直连你自己的发信服务器
- `config.json`（含授权码）、`reports/`、`pending.json`、`atm_cache/` 都在 `.gitignore` 里

---

## 已知限制

- **只能本地跑**：公文通要登录态，云端沙箱没有。电脑关机当天就不发（有补跑机制兜底）
- **PDF 附件多数抽不出中文**：中文 PDF 常用自定义编码，抽不出就跳过，不会编造内容
- **学校改版会失效**：依赖 szu-cli 的适配，报 `PAGE_CHANGED` 就是该更新了
- **跨年日期**：12 月发、写"1 月 5 日截止"的通知，部分判断仍可能偏差

---

## 免责

非官方项目，与深圳大学无关。数据来源 [szu-cli](https://github.com/AwesomeHou/szu-cli)（深大学生自制）。
使用前请自行确认符合学校相关规定。

MIT License.

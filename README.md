# 北航学院路羽毛球自动预约

已固定为学院路主馆。日期和时段尚未确定，因此配置默认关闭，定时任务也未安装。
程序可按北京时间 07:00 放场规则，查询、选择场地、创建并核对待支付订单。付款由你在官方页面完成。

项目已迁移至 `D:\Desktop\Projects\buaa-booking`，独立运行环境已在新位置重建。以后双击 **`启动.cmd`** 打开统一入口。账号、手机号和同伴资料已保留。

## 新版桌面界面

四个窗口统一使用现代桌面控件：预约任务、查看余场、账号与同伴、通知设置。
任务页分为“定时抢场”和“立即预约”，支持日历选日期、按姓名勾选同伴、上移备选时段和小窗口滚动。
通知配置已改为图形界面，点击“测试已保存的提醒”才会发消息。测试页独立存放，不会覆盖真实订单付款页。

## 日常使用

- **查余场**：启动窗口 → 查看余场。
- **预约已经放出的场地**：添加时段并设置总价上限 → 切换到“立即预约”页签并填写打球日期 → 先只查询，再点“立即预约”。
- **定时抢未来的场地**：选择具体打球日期或每周几 → 添加首选和备选时段 → 预览抢场时间 → 启用定时抢场。
- **暂停**：点击“暂停自动抢场”。关闭窗口不会暂停已安装的定时任务。

填写的是**打球日期**，程序按提前两天 07:00 的规则计算抢场时间，06:55 启动预热。例如想在 10 月 19 日打球，应在 10 月 17 日早上抢场。
“保存草稿”只保存草稿；“启用定时抢场”会重新检查登录和同伴，再安装或更新本目录的 Windows 任务。
立即预约使用独立的一次性规则，不会开启或改写日常定时任务。成功后从提醒、本地订单页或官方“我的订单”付款；官方要求 1 分钟内完成。

图文操作说明：双击 `开始使用.html`。命令行检查入口已收进 `高级工具` 文件夹。
从源码压缩包解压到新位置时，先运行 `安装.cmd` 重建环境，不要移动或复制 `.venv`。
本次验证范围见 `VALIDATION.md`；现已完成一次真实主馆订单及本人付款验证；退款仍由本人在官方订单页操作。

## 先验证

已登录后，双击 **`查看余场.cmd`** 打开余场界面。按今天、明天、后天分栏，显示时段、剩余场地数量和价格。
不显示场地编号；点击“刷新余场”重新查询。切换“连续2小时”时，只统计同一场地连续空闲的数量，并显示两小时总价。
这个界面只查余场，不会提交或取消订单。

1. 双击 `安装.cmd` 安装依赖。需要 Windows 和 Python 3.12 或以上版本；已安装 uv 时优先使用 uv。
2. 双击 `高级工具\验证.cmd`。它检查模型、运行离线演示、检查公开登录入口；不会登录或占场。
3. 双击 `账号验证.cmd`，在本机窗口输入学工号和统一认证密码。只登录和读取主馆信息，不创建订单。`高级工具\登录并查场.cmd` 提供同样目的的命令行入口。
4. 在“账号与同伴”窗口补充手机号，按姓名勾选实际同行的人，再点击“保存预约资料”。不需要填写内部 ID。
5. 双击 `配置通知.cmd` 配置 Bark key 和邮箱 SMTP 授权码。桌面通知、Bark、邮件都支持；未填写凭据的渠道不会发送。

凭据和令牌使用 Windows DPAPI 加密，保存在 `data/credentials.dpapi`，绑定当前 Windows 账户。
不要把此文件、`data/`、验证码截图或包含私人信息的配置发到公开仓库。

在项目文件夹打开 PowerShell，以下命令都使用本项目环境：

```powershell
.venv\Scripts\python.exe -m buaa_booking plan
.venv\Scripts\python.exe -m buaa_booking check
.venv\Scripts\python.exe -m buaa_booking details
.venv\Scripts\python.exe -m buaa_booking notify-test --send
```

`notify-test` 不加 `--send` 时只生成本地页。`data/notification-status.json` 分别记录三个渠道的结果。
桌面通知需要当前 Windows 用户会话；免打扰设置可能隐藏通知。Bark 和邮件可作为手机提醒。

## 确定打球规则后

编辑 `config.json`。例如，下面片段表示每周二、四打球，优先 19–21 点，备选 20–22 点，任意场地：

```json
{
  "enabled": false,
  "venue_site_id": 38,
  "dates": [],
  "weekdays": [2, 4],
  "release_lead_days": 2,
  "release_time": "07:00:00",
  "window_seconds": 60,
  "poll_seconds": 1.0,
  "max_submissions": 3,
  "max_total_price": "100.00",
  "same_court": true,
  "preferences": [
    {"start": "19:00", "end": "21:00", "courts": []},
    {"start": "20:00", "end": "22:00", "courts": []}
  ],
  "notifications": {"desktop": true, "bark": true, "email": true}
}
```

这只是示例，不是已启用的预约需求。`weekdays` 指打球的星期，1 为周一，7 为周日。
`dates` 可填具体打球日期，如 `2026-11-01`；两类日期按并集合并。不要默认“后天”就是想打球的日期。
当前已读到官方规则：每天 07:00 开放含当天的 3 天，因此 `release_lead_days=2`；所有时间使用北京时间。
主馆 `venue_site_id=38`，副馆为 `39`；执行时仍核对服务器返回的场馆 ID。

`courts: []` 接受任意场地。`courts: ["3号", "4号"]` 仅接受这两块，依次尝试。
额外设置 `allow_other_courts: true` 可让其余场地成为备选。
默认两小时必须是同一场地，且时间真正连续。只有 `same_court: false` 才允许中途换场。
首版支持连续一小时或两小时；不会自行缩短时长。

先运行以下命令：

```powershell
# 默认仅查询符合条件的方案，不获取验证码、不提交订单
.venv\Scripts\python.exe -m buaa_booking run --date 2026-11-01

# 按正常流程获取并校验验证码，停在发送订单前
.venv\Scripts\python.exe -m buaa_booking run --date 2026-11-01 --rehearse
```

确认日期、价格、场地和提醒正常后，再设 `enabled=true`。真实提交必须同时满足：
配置启用、日期符合配置、明确传入 `--execute`。

```powershell
# 立即尝试一次真实预约，成功后监测付款
.venv\Scripts\python.exe -m buaa_booking run --date 2026-11-01 --execute --watch

# 查看定时任务方案，不安装
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\Install-Task.ps1

# 最近 24 小时内 check 通过且配置已启用，才可安装
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\Install-Task.ps1 -Enable
```

任务默认每天 06:55 唤醒并预热；启动时和放场前依据学校预约网站的 HTTP 时间参考校准，按单调时钟等到 07:00 开始查询和提交。验证码尽量提前完成，一次使用。HTTP 时间仍有整秒和网络误差，不代表后台毫秒授时。任务仅在对应打球日期有规则时执行。
Windows 时区需要为 UTC+8。当前 Windows 账户需保持登录；锁屏可以，关机不能执行。
唤醒能力受设备电源设置影响，首次使用需要测试。超过本次抢场窗口才启动时，不会迟到下单。

移除任务：`powershell -NoProfile -ExecutionPolicy Bypass -File scripts\Uninstall-Task.ps1`。
设置 `enabled=false` 也会阻止真实提交。

## 订单、付款与异常

- 成功后先核对订单的日期、场地、时段、金额和状态，再显示付款入口。
- 本地订单页：`data/latest-order.html`。付款截止时间取自服务器 `expireTime`，不假定固定十分钟。
- 只创建官方付款页面，不读取支付密码，也不调用收银台的扣款流程。
- 同一账号同一打球日期，已有订单或结果不明确时，不再创建下一单。修改场地配置不会解除这个限制。
- 场地明确冲突时尝试备选。限流时退避；窗口和总提交次数均有上限。
- 提交响应丢失时记为 `unknown`。若没有拿到订单号，必须先在官方“我的订单”核对；程序不会猜测后重发。
- 如拿到正确订单号，可恢复核对：

```powershell
.venv\Scripts\python.exe -m buaa_booking recover --date 2026-11-01 --trade-no DXXXXXXXXXXXX
.venv\Scripts\python.exe -m buaa_booking status
```

恢复命令只查询已有订单，不新建或取消订单。若官方确认没有建单，保留记录并人工处理该次预约；首版不提供删除保护记录后重抢的快捷方式。
通知发送失败不会让已成功的预约重新提交。`--watch` 每五秒读一次订单，剩余不足一分钟提醒一次，并在付款完成或截止后结束；最长监测二十分钟。

## 离线验证与开发

```powershell
.venv\Scripts\python.exe -m buaa_booking demo --scenario success
.venv\Scripts\python.exe -m buaa_booking demo --scenario conflict
.venv\Scripts\python.exe -m buaa_booking demo --scenario timeout
.venv\Scripts\python.exe -m pytest
```

演示使用独立的临时订单库，结果页明确标为“离线演示，不是真实订单”；它不会发送校园请求或通知。
开发时可使用 `uv pip install --python .venv\Scripts\python.exe -e ".[ocr,test]"`。
`requirements.lock` 固定本次验收的运行依赖版本。

基于 MIT 项目 BH_CGYY 的 CLI 核心。固定上游版本、保留内容与修改范围见 `UPSTREAM.md`。


## 抢场失败排查

在项目目录执行 `.venv\Scripts\python.exe -m buaa_booking diagnostics`，查看本机脱敏诊断。记录包含学校时间参考、验证码来源与年龄、提交起止、耗时、业务码和具体说明；不包含请求正文、认证头或验证码密钥。

只对明确未成功的验证码拒绝、尚未放场、场地冲突和限流做有限重试。最多准备 3 次、提交 3 次，仍受配置的抢场窗口限制。普通服务器异常、超时或结果矛盾时停止重发并核对订单。未知业务码不能单凭数字判断为可重试。

校时使用网站 HTTP Date，有估计误差；验证码和抢场存在失败可能。离线测试与提交前演练不代表真实预约成功。

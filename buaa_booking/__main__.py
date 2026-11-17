from __future__ import annotations

import argparse
import getpass
import json
import logging
import os
import shutil
import sys
import tempfile
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

from buaa_booking.config import CHINA, Preference, load_config

ROOT = Path(__file__).resolve().parents[1]


def parser():
    p = argparse.ArgumentParser(description="北航学院路羽毛球预约：先验证，再启用定时提交")
    p.add_argument("--config", type=Path, default=ROOT / "config.json")
    sub = p.add_subparsers(dest="command", required=True)
    for name, help_text in (("init", "创建未启用的主馆配置"), ("plan", "离线查看预约计划"),
                            ("login", "本机输入统一认证凭据，使用 Windows 账户加密"),
                            ("details", "修改预约手机号和同伴 ID，不重复输入密码"),
                            ("board", "打开按日期、时段、数量和价格汇总的余场界面"),
                            ("clock-check", "只读核对预约网站时间、时差与估计误差"),
                            ("diagnostics", "查看本机脱敏执行诊断，不访问学校或创建订单"),
                            ("notifications", "配置 Bark 和邮件凭据"), ("status", "查看上次订单记录"),
                            ("network-check", "只访问公开登录入口，不登录或预约"),
                            ("selfcheck", "检查本机依赖与中文字体，不访问网络")):
        sub.add_parser(name, help=help_text)
    check = sub.add_parser("check", help="真实登录及只读查场，显示当前账号同伴列表，不下单")
    check.add_argument("--date", type=date.fromisoformat)
    run = sub.add_parser("run", help="默认只查场；明确 --execute 才提交订单")
    run.add_argument("--date", type=date.fromisoformat)
    run.add_argument("--execute", action="store_true")
    run.add_argument("--scheduled", action="store_true", help="等待放场时刻，错过窗口则退出")
    run.add_argument("--rehearse", action="store_true", help="校验验证码后结束，不提交订单")
    run.add_argument("--watch", action="store_true", help="真实建单后监测付款并在截止前提醒")
    run.add_argument("--open-payment", action="store_true", help="订单核对通过后先打开付款页，再发送提醒")
    recovery = sub.add_parser("recover", help="按你从官方页面核对的订单号恢复记录；不创建订单")
    recovery.add_argument("--date", type=date.fromisoformat, required=True)
    recovery.add_argument("--trade-no", required=True)
    demo = sub.add_parser("demo", help="离线演示完整流程，没有校园网络请求")
    demo.add_argument("--scenario", choices=("success", "conflict", "timeout"), default="success")
    nt = sub.add_parser("notify-test", help="测试通知，需明确 --send 才发送")
    nt.add_argument("--send", action="store_true")
    return p


def print_record(record):
    from buaa_booking.notify import order_message
    print(order_message(record))


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    # The app does not print auth internals or request URLs to a scheduled log.
    logging.getLogger().addHandler(logging.NullHandler())
    logging.getLogger().setLevel(logging.CRITICAL)
    if args.command == "init":
        if args.config.exists():
            print("配置已存在，未覆盖：" + str(args.config.resolve()))
        else:
            args.config.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "config.example.json", args.config)
            print("已创建主馆配置，自动预约未启用：" + str(args.config.resolve()))
        return 0
    if args.command == "network-check":
        import requests
        failed = False
        with requests.Session() as session:
            session.trust_env = False
            for url in ("https://cgyy.buaa.edu.cn/venue/home", "https://sso.buaa.edu.cn/login"):
                try:
                    response = session.get(url, timeout=10, allow_redirects=False)
                    print(f"{url}: HTTP {response.status_code}")
                    failed |= response.status_code >= 400
                except requests.RequestException as exc:
                    print(f"{url}: 无法连接（{type(exc).__name__}）")
                    failed = True
        print("未登录，未请求订单接口。")
        return 2 if failed else 0
    config = load_config(args.config)
    directory = config.path.parent / "data"
    if args.command == "clock-check":
        from buaa_booking.timing import SchoolClock
        print(json.dumps(SchoolClock(directory).synchronize(), ensure_ascii=False, indent=2))
        return 0
    if args.command == "board":
        from buaa_booking.availability_ui import main as show_board
        show_board(["--config", str(config.path)])
        return 0
    if args.command == "run" and args.scheduled and not config.enabled:
        print("自动预约未启用，未登录或提交订单。")
        return 0
    if args.command == "plan":
        print("场馆：学院路主馆羽毛球" if config.venue_site_id == 38 else "场馆：学院路副馆羽毛球")
        print("自动预约：" + ("已启用" if config.enabled else "未启用"))
        print("规则：提前 " + str(config.release_lead_days) + " 天 " + config.release_time.isoformat() + " 放场（需以官方规则核对）")
        if not config.preferences or not (config.dates or config.weekdays):
            print("日期或时段尚未设置；可以先运行 check 验证登录和查场。")
        for target, trigger in config.upcoming(datetime.now(CHINA)):
            print(f"打球 {target.isoformat()} → 北京时间 {trigger.isoformat()} 提交窗口")
        return 0
    if args.command == "selfcheck":
        import importlib.metadata
        from src.captcha_recognition import CaptchaRecognizer
        from src.captcha_recognition.matcher import _candidate_font_paths
        for name in ("requests", "pycryptodome", "ddddocr", "onnxruntime", "opencv-python", "Pillow"):
            print(f"{name}: {importlib.metadata.version(name)}")
        fonts = _candidate_font_paths()
        if not fonts:
            raise ValueError("没有找到中文字体，不能可靠执行验证码匹配")
        print("中文字体：" + ", ".join(p.name for p in fonts))
        model = CaptchaRecognizer()
        print("OCR 检测和识别模型已加载；没有发送网络请求。")
        del model
        return 0
    from buaa_booking.journal import Journal, run_lock
    from buaa_booking.notify import Notifier
    from buaa_booking.vault import Vault
    if args.command == "demo":
        from buaa_booking.demo import DemoAdapter, DemoClock
        from buaa_booking.engine import Engine
        clock = DemoClock()
        target = clock.now().date() + timedelta(days=2)
        sample = replace(config, enabled=True, venue_site_id=38, release_lead_days=2,
                         dates=(target,), preferences=(Preference("19:00", "21:00"),))
        notifier = Notifier(directory / "demo", {})
        with tempfile.TemporaryDirectory(prefix="buaa-demo-") as temp:
            journal = Journal(Path(temp))
            try:
                result = Engine(sample, DemoAdapter(target.isoformat(), clock, args.scenario), journal,
                                lambda r: notifier(r | {"demo": True}, external=False), clock).run(target, execute=True)
            finally:
                journal.close()
        result["demo"] = True
        notifier(result, external=False)
        print_record(result)
        print("演示订单页：" + str(directory / "demo" / "latest-order.html"))
        return 0
    if args.command in {"status", "diagnostics"}:
        journal = Journal(directory)
        try:
            if args.command == "diagnostics":
                print(json.dumps(journal.diagnostics(), ensure_ascii=False, indent=2))
            else:
                record = journal.latest()
                print_record(record) if record else print("暂无真实订单执行记录。")
        finally:
            journal.close()
        return 0
    vault = Vault(directory)
    with run_lock(directory):
        if args.command in ("login", "details", "notifications"):
            secrets = vault.read()
            if args.command == "login":
                username = input("北航学工号：").strip()
                password = getpass.getpass("统一认证密码（不会显示）：")
                if not username or not password:
                    raise ValueError("账号和密码不能为空")
                secrets.update(username=username, password=password, cookie="", cg_authorization="")
                secrets["phone"] = input("预约手机号（暂不填可直接回车）：").strip()
                secrets["buddy_ids"] = input("同伴 ID，逗号分隔（可先留空，check 查看列表后补充）：").strip()
                vault.write(secrets)
                print("凭据已使用当前 Windows 账户加密。下一步运行 check；此命令未下单。")
            elif args.command == "details":
                if not secrets.get("username"):
                    raise ValueError("请先运行 login")
                secrets["phone"] = input("预约手机号：").strip()
                secrets["buddy_ids"] = input("同伴 ID，逗号分隔：").strip()
                vault.write(secrets)
                print("预约资料已保存。请运行 check 核对。")
            else:
                bark = getpass.getpass("Bark device key（留空保留原值）：").strip()
                if bark:
                    secrets["bark_key"] = bark
                host = input("SMTP 服务器（留空跳过邮件配置）：").strip()
                if host:
                    secrets.update(smtp_host=host, smtp_port=int(input("SMTP 端口 [465]：").strip() or "465"),
                                   smtp_username=input("发件邮箱：").strip(), email_to=input("收件邮箱：").strip(),
                                   smtp_password=getpass.getpass("邮箱授权码（不会显示）："))
                vault.write(secrets)
                print("通知凭据已加密保存；未发送消息。使用 notify-test --send 测试。")
            return 0
        secrets = vault.read()
        notifier = Notifier(directory, config.notifications, secrets,
                            open_payment=args.command == "run" and args.execute and args.open_payment)
        if args.command == "notify-test":
            record = {"status": "test", "message": "北航预约通知测试，没有创建订单。"}
            notifier(record, external=args.send)
            print("测试结果：" + str(directory / "notification-status.json") if args.send else "仅生成本地测试页；未发送通知。")
            return 0
        from buaa_booking.adapter import LiveAdapter
        from buaa_booking.engine import Engine, candidate_from_dict
        try:
            adapter = LiveAdapter(config, vault)
        except Exception:
            notifier({"status": "error", "message": "账号资料未就绪，请在本机运行 login 和 check。"})
            raise
        if args.command == "check":
            adapter.authenticate()
            target = args.date or datetime.now(CHINA).date()
            info = adapter.query(target.isoformat())
            site = info.site_param
            print(f"登录和只读查询通过：{site.campus_name} / {site.venue_name} / {site.site_name}")
            print("返回日期：" + ", ".join(info.space_schedules_by_date))
            print(f"同伴要求：{site.buddy_num_min} 至 {site.buddy_num_max} 人")
            if info.order_param_view:
                for buddy in info.order_param_view.buddy_list:
                    print(f"同伴 ID={buddy.id}，姓名={buddy.name}")
            try:
                adapter.validate_buddies(info)
                print("预约资料检查通过。")
                ready = True
            except ValueError as exc:
                print("预约资料尚未齐全：" + str(exc))
                ready = False
            from buaa_booking.notify import atomic_text
            atomic_text(directory / "preflight.json", json.dumps({"ready": ready,
                "venue_site_id": config.venue_site_id, "checked_at": datetime.now(CHINA).isoformat()}, ensure_ascii=False))
            print("本次没有获取验证码，没有提交订单。")
            return 0 if ready else 2
        journal = Journal(directory)
        engine = Engine(config, adapter, journal, notifier)
        try:
            if args.command == "recover":
                key = f"{adapter.account_id}:{args.date.isoformat()}"
                record = journal.get(key)
                if not record or not record.get("candidate"):
                    raise ValueError("本机没有该日期的提交记录，无法自动核对")
                if record["status"] not in {"submitting", "unknown", "submitted", "needs_review", "pending_payment"}:
                    raise ValueError("当前记录不需要恢复")
                adapter.authenticate()
                journal.save(key, "submitted", trade_no=args.trade_no)
                result = engine.confirm(key, args.trade_no, candidate_from_dict(record["candidate"]))
            else:
                now = datetime.now(CHINA)
                target = args.date or config.today_target(now)
                if args.scheduled and args.date is None:
                    tomorrow_target = target + timedelta(days=1)
                    seconds = (config.release_at(tomorrow_target) - now).total_seconds()
                    if 0 < seconds <= 300:
                        target = tomorrow_target
                if args.scheduled and not config.eligible(target):
                    print("今天不对应已配置的打球日期，未执行预约。")
                    return 0
                result = engine.run(target, execute=args.execute, scheduled=args.scheduled, rehearse=args.rehearse)
                if args.watch and args.execute:
                    result = engine.watch(result)
            if result.get("status") in {"dry_run", "rehearsed", "no_availability"}:
                notifier(result, external=False)
            print_record(result)
            return 0 if result.get("status") in {"dry_run", "rehearsed", "pending_payment", "paid"} else 2
        except Exception as exc:
            notifier({"status": "error", "message": f"本次运行未完成（{type(exc).__name__}）。请检查本地状态并核对官方订单。"})
            raise
        finally:
            journal.close()


def entrypoint():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    try:
        return main()
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        print("配置或资料未就绪：" + str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("已停止；如已开始提交，请先检查官方订单。", file=sys.stderr)
        return 130
    except Exception as exc:
        # Exception strings can contain tokens or login form data.
        print(f"运行未完成（{type(exc).__name__}）。请先运行 network-check 和 check 核对连接及登录。", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())

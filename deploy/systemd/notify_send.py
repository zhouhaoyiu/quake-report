#!/usr/bin/env python3
"""quake-report 出图通知发送脚本（由 systemd timer 每 2 分钟调用）。

读取 /opt/quake-report-cache/notify-queue.jsonl（generate 成功后追加），
逐条通过 163 SMTP 发送文字通知邮件，成功后从队列移除。
配置读取 /etc/quake-report/notify.conf：
  SMTP_USER=18811713109@163.com
  SMTP_AUTH_CODE=<163 邮箱授权码>
  TO=18811713109@163.com
"""
import json
import os
import smtplib
import sys
from datetime import datetime, timezone, timedelta
from email.header import Header
from email.mime.text import MIMEText
from pathlib import Path

QUEUE = Path(os.environ.get("QUAKE_NOTIFY_QUEUE", "/opt/quake-report-cache/notify-queue.jsonl"))
SENT = Path("/opt/quake-report-cache/notify-sent.jsonl")
CONF = Path("/etc/quake-report/notify.conf")
LOG = Path("/opt/quake-report-cache/notify.log")
MAX_PER_RUN = 5
TZ = timezone(timedelta(hours=8))


def log(msg: str) -> None:
    line = f"{datetime.now(TZ).isoformat()} {msg}\n"
    try:
        with LOG.open("a") as f:
            f.write(line)
    except Exception:
        pass


def load_conf() -> dict:
    conf: dict[str, str] = {}
    if CONF.exists():
        for line in CONF.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            conf[k.strip()] = v.strip()
    return conf


def build_body(entry: dict) -> str:
    ms = entry.get("mainshock") or {}
    names = entry.get("fileNames") or {}
    try:
        ts = datetime.fromisoformat(entry.get("ts", "").replace("Z", "+00:00")).astimezone(TZ)
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        ts_str = entry.get("ts", "")

    place = ms.get("place") or "未知地点"
    mag = ms.get("magnitude")
    mag_type = ms.get("mag_type") or "M"
    try:
        t = datetime.fromisoformat(str(ms.get("time_utc", "")).replace("Z", "+00:00")).astimezone(TZ)
        quake_time = t.strftime("%Y-%m-%d %H:%M")
    except Exception:
        quake_time = str(ms.get("time_utc") or "未知")

    lines = [
        "【地震速报系统】新的出图通知",
        "",
        f"出图时间：{ts_str}（北京时间）",
        f"地震事件：{place} {mag_type}{mag}级",
        f"发震时刻：{quake_time}（北京时间）",
        f"震中位置：{ms.get('latitude', '?')}°N, {ms.get('longitude', '?')}°E",
        f"震源深度：{ms.get('depth_km', '?')} km",
        "",
        "生成文件：",
    ]
    if names.get("map"):
        lines.append(f"  - 分布图：{names['map']}")
    if names.get("catalog"):
        lines.append(f"  - 目录：{names['catalog']}")
    if names.get("docx"):
        lines.append(f"  - Word 报告：{names['docx']}")
    if names.get("pdf"):
        lines.append(f"  - PDF：{names['pdf']}")
    lines.append("")
    lines.append("（本邮件由系统自动发送，请勿回复）")
    return "\n".join(lines)


def send_mail(conf: dict, body: str) -> None:
    user = conf["SMTP_USER"]
    code = conf["SMTP_AUTH_CODE"]
    to = conf.get("TO", user)
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header("地震速报系统：新的出图通知", "utf-8")
    msg["From"] = user
    msg["To"] = to
    with smtplib.SMTP_SSL("smtp.163.com", 465, timeout=30) as s:
        s.login(user, code)
        s.sendmail(user, [to], msg.as_string())


def main() -> int:
    conf = load_conf()
    if "SMTP_AUTH_CODE" not in conf or not conf["SMTP_AUTH_CODE"]:
        log("SKIP 未配置 SMTP_AUTH_CODE（/etc/quake-report/notify.conf）")
        return 0
    if not QUEUE.exists():
        return 0
    lines = QUEUE.read_text().splitlines()
    if not lines:
        return 0

    remaining, sent_count, failed = [], 0, 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except Exception:
            continue
        if sent_count >= MAX_PER_RUN:
            remaining.append(line)
            continue
        try:
            send_mail(conf, build_body(entry))
            with SENT.open("a") as f:
                f.write(line + "\n")
            sent_count += 1
            log(f"SENT {entry.get('ts', '')} -> {conf.get('TO', conf['SMTP_USER'])}")
        except Exception as e:
            failed += 1
            log(f"FAIL {entry.get('ts', '')}: {e}")
            remaining.append(line)

    if sent_count:
        QUEUE.write_text("\n".join(remaining) + ("\n" if remaining else ""))
    log(f"DONE sent={sent_count} failed={failed} remaining={len(remaining)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

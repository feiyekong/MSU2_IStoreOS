"""页面渲染：网速页 / 系统页 / 时钟页（160x80）"""
import time

from . import canvas as C
from . import font
from .metrics import fmt_speed, fmt_uptime

TITLE = C.rgb(120, 200, 255)
LABEL = C.rgb(170, 170, 170)
DOWN_C = C.rgb(0, 220, 255)
UP_C = C.rgb(255, 150, 40)
CPU_C = C.rgb(90, 230, 120)
TEMP_C = C.rgb(255, 90, 90)
MEM_C = C.rgb(230, 210, 60)
CLI_C = C.rgb(140, 230, 160)

HIST_LEN = 156


def _right(cv, x_right, y, s, color, scale=1, spacing=1):
    w = cv.text_w(s, scale, spacing)
    cv.text(x_right - w, y, s, color, scale, spacing)
    return w


def _speed_row(cv, y, icon, num, unit, color, right=156, max_scale=3):
    """一行速度：左侧图标 + 右侧大号数值 + 单位（自动选字号）"""
    scale = 2
    for sc in range(max_scale, 1, -1):
        if cv.text_w(num, sc) + 5 + cv.text_w(unit, 1) <= (right - 24 - 40):
            scale = sc
            break
    nw = cv.text_w(num, scale)
    uw = cv.text_w(unit, 1)
    x0 = right - (nw + 5 + uw)
    cv.text(x0, y, num, color, scale)
    cv.text(x0 + nw + 5, y + font.GH * scale - font.GH, unit, color, 1)
    # 左侧图标（垂直居中于数字）
    iy = y + (font.GH * scale - 16) // 2
    if icon == "down":
        cv.icon_download(2, iy, 16, color)
    else:
        cv.icon_upload(2, iy, 16, color)
    return y + font.GH * scale


def render_net(cv, m, hist):
    """网速页：外网IP + 网口协商速率 + 当前上下行速度（带上下行图标，无曲线）"""
    cv.clear(C.BLACK)

    rx, tx, rx_tot, tx_tot = m.net_speed()
    rx_s, rx_u = fmt_speed(rx)
    tx_s, tx_u = fmt_speed(tx)

    # ---- 顶部：WAN 链路协商速率 ----
    phys = m.wan_phys()
    mbps, duplex = m.link_speed(phys)
    cv.text(2, 1, "WAN", TITLE, 1)
    link = "%s %s" % (m.speed_text(mbps), "FULL" if duplex == "full" else (duplex or "").upper()[:4])
    _right(cv, 156, 1, link.strip(), LABEL, 1)

    # ---- 下行 ----
    _speed_row(cv, 10, "down", rx_s, rx_u, DOWN_C)
    cv.hline(2, 35, 154, C.rgb(45, 45, 45))
    # ---- 上行 ----
    _speed_row(cv, 40, "up", tx_s, tx_u, UP_C)

    # ---- 底部：WAN 口当前 IP（直接显示运营商分配给本机 WAN 口的地址）----
    from .metrics import iface_ip, is_cgnat
    wan_ip = iface_ip(getattr(m, "wan", None)) or iface_ip("pppoe-wan")
    if wan_ip:
        nat = is_cgnat(wan_ip)
        cv.text(2, 70, "WAN", LABEL, 1)
        cv.text(22, 70, wan_ip, C.rgb(120, 220, 150) if not nat else C.rgb(200, 200, 200), 1)
        if nat:      # 运营商大内网，标记出来
            _right(cv, 156, 70, "NAT", C.rgb(255, 160, 60), 1)

    return rx, tx


def render_sys(cv, m, hist):
    """系统页：CPU 占用 / 温度 / 内存（各带进度条）"""
    cv.clear(C.BLACK)
    cpu = m.cpu_percent()
    temp = m.cpu_temp()
    mem_pct, mem_used, mem_total = m.mem()
    load = m.loadavg()[0]

    cv.text(2, 1, "SYSTEM", LABEL, 1)
    _right(cv, 156, 1, "UP " + fmt_uptime(m.uptime()), LABEL, 1)

    rows = [
        ("CPU", "%4.1f%%" % cpu, cpu / 100.0, CPU_C),
        ("TEMP", ("%4.1f\u00b0C" % temp) if temp is not None else "--", (temp or 0) / 100.0, TEMP_C),
        ("MEM", "%4.1f%%" % mem_pct, mem_pct / 100.0, MEM_C),
    ]
    y = 9
    for name, val, frac, col in rows:
        cv.text(2, y + 4, name, LABEL, 1)
        _right(cv, 156, y, val, col, 2)
        cv.bar(2, y + 16, 156, 5, frac, col, C.DGRAY)
        y += 23
    return cpu, temp, mem_pct, load


def render_clock(cv, m, hist, tz_offset=0):
    """时钟页：大号时间 + 秒 + 在线客户端数 + 日期星期"""
    cv.clear(C.BLACK)
    # 默认直接用系统本地时间（路由器时区已由 uci/TZ 配置好，切勿再加偏移）
    t = time.localtime(time.time() + tz_offset * 3600) if tz_offset else time.localtime()
    hhmm = time.strftime("%H:%M", t)
    ss = time.strftime("%S", t)
    date = time.strftime("%Y-%m-%d", t)
    wd = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"][t.tm_wday]

    # 大号时间
    w = cv.text_w(hhmm, 3)
    cv.text((160 - w) // 2, 7, hhmm, C.WHITE, 3)
    # 秒
    cv.text((160 - cv.text_w(ss, 2)) // 2, 33, ss, C.rgb(0, 220, 255), 2)
    # 在线客户端数
    n = m.clients()
    cli_txt = "CLIENTS %d" % n if n is not None else "CLIENTS --"
    cw = cv.text_w(cli_txt, 1)
    cv.text((160 - cw) // 2, 53, cli_txt, CLI_C, 1)
    # 日期 / 星期
    cv.text(2, 69, date, LABEL, 1)
    _right(cv, 156, 69, wd, LABEL, 1)
    return hhmm

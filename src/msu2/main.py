#!/usr/bin/env python3
"""MSU2 小屏幕主程序：显示实时网速 / CPU 温度 / 内存占用 / 负载

用法：
  python3 -m msu2.main --page auto --interval 1 --rotate 15
  python3 -m msu2.main --page net --once
"""
import argparse
import os
import signal
import sys
import time

from . import canvas as C
from . import pages
from .metrics import Metrics
from .transport import Screen, ScreenError

HIST_MAX = 156
STATE_FILE = "/tmp/msu2d.status"      # 供 LuCI 页面显示真实运行状态


UCI_CONFIG = "/etc/config/msu2"


def load_uci_config(path=UCI_CONFIG, section="settings"):
    """读取 /etc/config/msu2 的 settings 段（纯文本解析，不调用 uci 命令）

    由 LuCI 页面（服务 -> USB副屏）写入，字段：
      enabled  0/1     是否显示
      page     auto|net|sys|clock
      interval 秒      刷新间隔
      rotate   秒      轮播每页停留
    """
    cfg = {}
    cur = None
    try:
        with open(path, "r") as f:
            for ln in f:
                s = ln.strip()
                if not s or s.startswith("#"):
                    continue
                parts = s.split(None, 2)
                if parts[0] == "config":
                    cur = parts[2].strip("'\"") if len(parts) >= 3 else None
                elif cur == section and parts[0] == "option" and len(parts) >= 3:
                    cfg[parts[1]] = parts[2].strip().strip("'\"")
    except OSError:
        pass
    return cfg


def _as_float(v, default):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def build_parser():
    ap = argparse.ArgumentParser(description="MSU2 USB 屏幕显示实时系统指标")
    ap.add_argument("--device", default=None, help="串口设备（默认自动查找）")
    ap.add_argument("--page", default="auto", choices=["auto", "net", "sys", "clock"])
    ap.add_argument("--interval", type=float, default=1.0, help="刷新间隔（秒）")
    ap.add_argument("--rotate", type=float, default=15.0, help="auto 模式每页停留秒数")
    ap.add_argument("--once", action="store_true", help="只刷新一帧后退出")
    ap.add_argument("--frames", type=int, default=0, help="最多刷新 N 帧后退出（0=不限）")
    ap.add_argument("--direction", type=int, default=0,
                    help="屏幕方向 0..7（0=正向 1=180° 2=水平镜像 3=垂直镜像 4=顺时针90° 5=逆时针90° 6/7=镜像+90°）")
    ap.add_argument("--quiet", action="store_true")
    return ap


class Runner(object):
    def __init__(self, args):
        self.args = args
        self.metrics = Metrics()
        self.wan = self.metrics.pick_wan()
        self.screen = Screen(args.device, verbose=not args.quiet,
                             direction=getattr(args, "direction", 0))
        self.hist = {"rx": [], "tx": [], "interval": args.interval}
        self.running = True
        self.frames = 0
        self.errors = 0
        self.page_start = time.time()
        self.current = "net" if args.page == "auto" else args.page

    # ---------- 生命周期 ----------
    def connect(self):
        self.screen.open()
        if self.screen.wait_standby(timeout=3.0):
            self.screen.handshake(timeout=1.5)
            w, h = self.screen.read_size()
            print("[main] 屏幕分辨率 %dx%d" % (w, h), flush=True)
        else:
            print("[main] 设备未处于待机态（可能已在显示中）", flush=True)
        self.screen.ensure_display()

    def recover(self):
        """写失败后的恢复：重开串口 -> 等待机 -> 握手 -> 重设区域"""
        print("[main] 尝试恢复连接…", flush=True)
        try:
            self.screen.close()
        except Exception:
            pass
        for attempt in range(5):
            if not self.running:
                return False
            time.sleep(1.0)
            try:
                self.screen.open()
                if self.screen.wait_standby(timeout=4.0):
                    self.screen.handshake(timeout=1.5)
                self.screen.ensure_display()
                print("[main] 已恢复（第 %d 次尝试）" % (attempt + 1), flush=True)
                return True
            except Exception as e:
                print("[main] 恢复失败：%s" % e, flush=True)
        print("[main] 恢复失败，设备可能需要断电重启（拔插 USB）", flush=True)
        return False

    # ---------- 页面 ----------
    def pick_page(self):
        if self.args.page != "auto":
            return self.args.page
        order = ["net", "sys", "clock"]
        idx = int((time.time() - self.page_start) // max(1.0, self.args.rotate)) % len(order)
        return order[idx]

    def render(self, page):
        cv = C.Canvas(self.screen.width, self.screen.height)
        if page == "net":
            rx, tx = pages.render_net(cv, self.metrics, self.hist)
            self.hist["rx"].append(rx)
            self.hist["tx"].append(tx)
            del self.hist["rx"][:-HIST_MAX]
            del self.hist["tx"][:-HIST_MAX]
        elif page == "sys":
            pages.render_sys(cv, self.metrics, self.hist)
        else:
            pages.render_clock(cv, self.metrics, self.hist)
        return cv

    def write_state(self):
        try:
            with open(STATE_FILE, "w") as f:
                f.write("pid=%d\n" % os.getpid())
                f.write("page=%s\n" % self.current)
                f.write("interval=%s\n" % self.args.interval)
                f.write("rotate=%s\n" % self.args.rotate)
                f.write("direction=%s\n" % getattr(self.args, "direction", 0))
                f.write("frames=%d\n" % self.frames)
                f.write("errors=%d\n" % self.errors)
                f.write("device=%s\n" % (self.screen.device or "-"))
        except Exception:
            pass

    # ---------- 主循环 ----------
    def run(self):
        self.connect()
        while self.running:
            t0 = time.time()
            page = self.pick_page()
            if page != self.current:
                self.current = page
                print("[main] 切换到页面：%s" % page, flush=True)
            try:
                cv = self.render(page)
                payload = cv.encode()
                self.screen.send_frame(payload)
                self.frames += 1
                self.write_state()
                if self.frames % 30 == 1:
                    print("[main] 第 %d 帧 页面=%s 数据=%d 字节" %
                          (self.frames, page, len(payload)), flush=True)
            except ScreenError as e:
                self.errors += 1
                print("[main] 写入异常：%s" % e, flush=True)
                if not self.recover():
                    break
            except Exception as e:
                print("[main] 异常：%s" % e, flush=True)
                time.sleep(1.0)
            if self.args.once:
                break
            if self.args.frames and self.frames >= self.args.frames:
                break
            dt = time.time() - t0
            time.sleep(max(0.0, self.args.interval - dt))
        self.screen.close()
        print("[main] 退出（共 %d 帧，异常 %d 次）" % (self.frames, self.errors), flush=True)


def main(argv=None):
    cfg = load_uci_config()
    if str(cfg.get("enabled", "1")).lower() not in ("1", "true", "yes", "on"):
        print("[main] 配置为「禁用显示」（/etc/config/msu2: enabled=0），退出", flush=True)
        return 0

    parser = build_parser()
    try:
        direction = int(cfg.get("direction", 0))
    except (TypeError, ValueError):
        direction = 0
    parser.set_defaults(
        page=cfg.get("page", "auto"),
        interval=_as_float(cfg.get("interval"), 1.0),
        rotate=_as_float(cfg.get("rotate"), 15.0),
        direction=direction,
    )
    args = parser.parse_args(argv)
    runner = Runner(args)

    def stop(signum, frame):
        runner.running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        runner.run()
    except ScreenError as e:
        print("[main] 致命错误：%s" % e, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

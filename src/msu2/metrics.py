"""系统指标采集（读 /proc /sys，仅标准库）"""
import os
import re
import time
import socket
import struct
import fcntl
import threading
import urllib.request

# 外网 IP 查询服务（按顺序尝试，HTTP 明文即可）
IP_SERVICES = (
    "http://ip.3322.net",
    "http://members.3322.org/dyndns/getip",
    "http://ifconfig.me/ip",
    "http://ipinfo.io/ip",
)
SIOCGIFADDR = 0x8915


def _read(path, default=None):
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except Exception:
        return default


def iface_ip(name):
    """读取网卡 IPv4 地址（ioctl，无需调用外部命令）"""
    if not name:
        return None
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        r = fcntl.ioctl(s.fileno(), SIOCGIFADDR, struct.pack("256s", name[:15].encode()))
        return socket.inet_ntoa(r[20:24])
    except Exception:
        return None
    finally:
        s.close()


def is_cgnat(ip):
    """是否运营商大内网地址(100.64.0.0/10)"""
    try:
        a, b = ip.split(".")[0:2]
        return int(a) == 100 and 64 <= int(b) <= 127
    except Exception:
        return False


class Metrics(object):
    def __init__(self, wan="pppoe-wan", lan="br-lan",
                 net_base="/sys/class/net",
                 temp_path="/sys/class/thermal/thermal_zone0/temp"):
        self.wan = wan
        self.lan = lan
        self.net_base = net_base
        self.temp_path = temp_path
        self._cpu_last = None
        self._cpu_time = None
        self._net_last = {}
        self._net_time = {}
        self.uptime_at_start = self.uptime()
        self.public_ip_enabled = True
        self._pub_ip = None
        self._pub_time = 0.0
        self._pub_lock = threading.Lock()
        self._pub_thread = None

    # ---------- 网络 ----------
    def net_counters(self, iface):
        base = os.path.join(self.net_base, iface, "statistics")
        rx = _read(os.path.join(base, "rx_bytes"))
        tx = _read(os.path.join(base, "tx_bytes"))
        if rx is None or tx is None:
            return None
        return int(rx), int(tx)

    def net_speed(self, iface=None):
        """返回 (rx_Bps, tx_Bps, rx_total, tx_total)；首次调用返回速度 0"""
        iface = iface or self.wan
        cur = self.net_counters(iface)
        now = time.monotonic()
        if cur is None:
            return 0.0, 0.0, 0, 0
        rx, tx = cur
        last = self._net_last.get(iface)
        last_t = self._net_time.get(iface)
        rxs = txs = 0.0
        if last and last_t and now > last_t:
            dt = now - last_t
            rxs = max(0.0, (rx - last[0]) / dt)
            txs = max(0.0, (tx - last[1]) / dt)
        self._net_last[iface] = (rx, tx)
        self._net_time[iface] = now
        return rxs, txs, rx, tx

    def iface_exists(self, iface):
        return os.path.isdir(os.path.join(self.net_base, iface))

    def pick_wan(self):
        """自动挑一个可用的 WAN 接口"""
        for cand in (self.wan, "pppoe-wan", "pppoe0", "eth1", "wan"):
            if self.iface_exists(cand):
                self.wan = cand
                return cand
        return self.wan

    # ---------- CPU ----------
    def _cpu_times(self):
        line = _read("/proc/stat")
        if not line:
            return None
        for ln in line.splitlines():
            if ln.startswith("cpu "):
                parts = [int(x) for x in ln.split()[1:]]
                idle = parts[3] + (parts[4] if len(parts) > 4 else 0)
                total = sum(parts)
                return idle, total
        return None

    def cpu_percent(self):
        cur = self._cpu_times()
        if not cur:
            return 0.0
        idle, total = cur
        pct = 0.0
        if self._cpu_last:
            di = idle - self._cpu_last[0]
            dt = total - self._cpu_last[1]
            if dt > 0:
                pct = 100.0 * (1.0 - float(di) / float(dt))
        self._cpu_last = (idle, total)
        if pct < 0:
            pct = 0.0
        if pct > 100:
            pct = 100.0
        return pct

    def cpu_temp(self):
        raw = _read(self.temp_path)
        if raw is None:
            # 退路：扫描 hwmon
            for zone in range(4):
                raw = _read("/sys/class/thermal/thermal_zone%d/temp" % zone)
                if raw:
                    break
        if raw is None:
            return None
        try:
            v = float(raw)
        except ValueError:
            return None
        if v > 1000:
            v = v / 1000.0
        return v

    # ---------- 内存 ----------
    def mem(self):
        info = {}
        txt = _read("/proc/meminfo")
        if not txt:
            return 0.0, 0, 0
        for ln in txt.splitlines():
            if ":" in ln:
                k, v = ln.split(":", 1)
                info[k.strip()] = v.strip()
        total = int(info.get("MemTotal", "0 kB").split()[0])
        avail = info.get("MemAvailable")
        if avail:
            avail = int(avail.split()[0])
        else:
            free = int(info.get("MemFree", "0 kB").split()[0])
            cached = int(info.get("Cached", "0 kB").split()[0])
            avail = free + cached
        used = max(0, total - avail)
        pct = (100.0 * used / total) if total else 0.0
        return pct, used / 1024.0, total / 1024.0     # pct, MB, MB



    # ---------- 链路速率（网口协商速率） ----------
    def wan_phys(self):
        """找出 WAN 对应的物理网口（从 /etc/config/network 的 wan 段读 device）"""
        try:
            cur = None
            with open("/etc/config/network", "r") as f:
                for ln in f:
                    t = ln.strip()
                    if t.startswith("config interface"):
                        cur = t.split()[-1].strip("'\"")
                    elif cur == "wan" and t.startswith("option device"):
                        dev = t.split()[-1].strip("'\"")
                        if os.path.isdir(os.path.join(self.net_base, dev)):
                            return dev
        except Exception:
            pass
        for cand in ("eth1", "eth0", "wan"):
            sp = os.path.join(self.net_base, cand, "speed")
            if os.path.exists(sp):
                return cand
        return None

    def link_speed(self, iface=None):
        """返回 (速率Mbps, 双工) ；读不到返回 (None, None)"""
        iface = iface or self.wan_phys()
        if not iface:
            return None, None
        sp = _read(os.path.join(self.net_base, iface, "speed"))
        dx = _read(os.path.join(self.net_base, iface, "duplex"))
        try:
            mbps = int(sp)
        except (TypeError, ValueError):
            mbps = None
        if mbps is not None and mbps <= 0:
            mbps = None
        return mbps, (dx or None)

    def speed_text(self, mbps):
        """把 Mbps 格式化为人类可读（1000 -> 1.0G）"""
        if not mbps:
            return "--"
        if mbps >= 1000:
            return "%.1fG" % (mbps / 1000.0)
        return "%dM" % mbps

    # ---------- 客户端（在线设备） ----------
    def client_list(self, iface="br-lan"):
        """ARP 表中状态完整(0x2)的条目 = 当前活跃客户端；返回 [(ip, mac, dev), ...]"""
        rows = []
        try:
            with open("/proc/net/arp") as f:
                next(f, None)
                for ln in f:
                    p = ln.split()
                    if len(p) < 6 or p[2] != "0x2":
                        continue
                    dev = p[5]
                    if dev.startswith("docker") or dev.startswith("veth"):
                        continue
                    if iface and dev != iface:
                        continue
                    rows.append((p[0], p[3], dev))
        except Exception:
            return []
        return rows

    def clients(self, iface="br-lan"):
        """在线客户端数量（ARP 活跃条目）；失败返回 None"""
        try:
            rows = self.client_list(iface)
            if not rows and iface:
                rows = self.client_list(None)      # 退路：不限接口
            return len(rows)
        except Exception:
            return None

    def dhcp_lease_count(self):
        """DHCP 已分配地址数（含离线设备，仅作参考）"""
        try:
            n = 0
            with open("/tmp/dhcp.leases") as f:
                for ln in f:
                    if len(ln.split()) >= 5:
                        n += 1
            return n
        except Exception:
            return None


    # ---------- 外网 IP ----------
    def _fetch_public_ip(self):
        for url in IP_SERVICES:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "curl/8.0"})
                with urllib.request.urlopen(req, timeout=4) as r:
                    txt = r.read(64).decode("utf-8", "ignore")
                m = re.search(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})", txt)
                if m:
                    return m.group(1)
            except Exception:
                continue
        return None

    def _pub_loop(self):
        while True:
            ip = self._fetch_public_ip()
            if ip:
                with self._pub_lock:
                    self._pub_ip = ip
                    self._pub_time = time.time()
            time.sleep(600)          # 10 分钟刷新一次

    def public_ip(self):
        """返回 (IP, 是否真公网)。外部服务拿不到时用本机 WAN 口地址兜底"""
        if self.public_ip_enabled:
            if self._pub_thread is None:
                self._pub_thread = threading.Thread(target=self._pub_loop, daemon=True)
                self._pub_thread.start()
            with self._pub_lock:
                ip = self._pub_ip
            if ip:
                return ip, True
        wan = iface_ip(self.wan) or iface_ip("pppoe-wan")
        if wan:
            return wan, not is_cgnat(wan)
        return None, False

    # ---------- 其它 ----------
    def loadavg(self):
        txt = _read("/proc/loadavg") or "0 0 0"
        try:
            parts = txt.split()
            return float(parts[0]), float(parts[1]), float(parts[2])
        except Exception:
            return 0.0, 0.0, 0.0

    def uptime(self):
        txt = _read("/proc/uptime") or "0"
        try:
            return float(txt.split()[0])
        except Exception:
            return 0.0


def fmt_speed(bps):
    """网速格式化 -> (数值字符串, 单位)

    统一以 KB/s 起步（1 位小数），避免空闲时只显示一个巨大的 "0"：
      0        -> 0.0 KB/s
      12.5 KB  -> 12.5 KB/s
      1.2 MB   -> 1.2 MB/s
      118 MB   -> 118.0 MB/s
    """
    if bps >= 1024 * 1024:
        return "%.1f" % (bps / (1024.0 * 1024.0)), "MB/s"
    return "%.1f" % (bps / 1024.0), "KB/s"


def fmt_uptime(sec):
    sec = int(sec)
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return "%dd%dh" % (d, h)
    if h:
        return "%dh%dm" % (h, m)
    return "%dm" % m

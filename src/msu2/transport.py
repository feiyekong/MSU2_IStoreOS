"""MSU2 屏幕串口传输层（仅标准库）

协议要点（已实测）：
  - 握手：           00 4D 53 4E 43 4E  (NUL + "MSNCN")  -> 回显一致
  - 设置显示区域：   02 00 xH xL yH yL | 02 01 wH wL hH hL | 02 03 07 00 00 00
  - 帧数据：         每 128 像素(256B) 一页：02 04 <bg4> / 04 <k> <v4> / 02 03 08 01 00 00
  - 读 SFR：         00 30 00 <addrH> <addrL> 00     -> 回显末字节为值
  - 读 ADC 按键：    08 09 00 00 00 00               -> 08 09 00 00 <adcH> <adcL>
  - 设置方向：       02 03 0A <dir> 00 00

设备行为：
  - 待机态：10Hz 发心跳（NUL+"MSN01"），所有指令都回显
  - 显示态：心跳停止、指令不再回显（正常）；只能靠"写入是否被消费"判断存活
  - 显示态下严禁重发 0x07（LCD_ADD）或在帧中间插入其它命令，否则固件会卡死（需断电）
"""
import os
import glob
import time
import fcntl
import struct
import select
import termios

MSN_HELLO = b"\x00MSNCN"
MSN_BEAT = b"\x00MSN01"

TIOCMBIS = 0x5416
TIOCOUTQ = 0x5411
TIOCINQ = 0x541B
DTR = 0x002
RTS = 0x004


def find_screen(vid_pid="1a86:fe0c"):
    """按 VID:PID 查找串口设备（默认 CH32x035）"""
    vid, pid = vid_pid.split(":")
    for tty in sorted(glob.glob("/sys/class/tty/ttyACM*") + glob.glob("/sys/class/tty/ttyUSB*")):
        try:
            base = os.path.realpath("/sys/class/tty/%s/device" % os.path.basename(tty))
            for _ in range(4):
                vendor = os.path.join(base, "idVendor")
                product = os.path.join(base, "idProduct")
                if os.path.exists(vendor) and os.path.exists(product):
                    with open(vendor) as f:
                        v = f.read().strip()
                    with open(product) as f:
                        p = f.read().strip()
                    if v.lower() == vid.lower() and p.lower() == pid.lower():
                        return "/dev/%s" % os.path.basename(tty)
                    break
                base = os.path.dirname(base)
        except Exception:
            continue
    for cand in ("/dev/ttyACM0", "/dev/ttyACM1"):
        if os.path.exists(cand):
            return cand
    return None


class ScreenError(Exception):
    pass


class Screen(object):
    def __init__(self, device=None, verbose=True, width=160, height=80, direction=0):
        self.device = device or find_screen()
        self.verbose = verbose
        self.width = width
        self.height = height
        self.direction = direction      # LCD 显示方向 0..7（0=正向，1=180°，2/3=镜像，4=顺时针90°...）
        self.fd = None
        self.display_mode = False
        self.last_error = None

    def log(self, *a):
        if self.verbose:
            print("[screen]", *a, flush=True)

    def open(self):
        if not self.device:
            raise ScreenError("找不到 MSU2 屏幕设备（VID:PID=1a86:fe0c）")
        self.fd = os.open(self.device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        a = termios.tcgetattr(self.fd)
        iflag, oflag, cflag, lflag, isp, osp, cc = a
        iflag &= ~(termios.IGNBRK | termios.BRKINT | termios.PARMRK | termios.ISTRIP |
                   termios.INLCR | termios.IGNCR | termios.ICRNL | termios.IXON)
        oflag &= ~termios.OPOST
        lflag &= ~(termios.ECHO | termios.ECHONL | termios.ICANON | termios.ISIG | termios.IEXTEN)
        cflag &= ~(termios.CSIZE | termios.PARENB)
        cflag |= termios.CS8
        cc[termios.VMIN] = 0
        cc[termios.VTIME] = 0
        termios.tcsetattr(self.fd, termios.TCSANOW, [iflag, oflag, cflag, lflag, isp, osp, cc])
        try:
            fcntl.ioctl(self.fd, TIOCMBIS, struct.pack("I", DTR | RTS))
        except Exception:
            pass
        self.display_mode = False
        self.log("已打开", self.device)
        return self.fd

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except Exception:
                pass
            self.fd = None

    def outq(self):
        try:
            return struct.unpack("I", fcntl.ioctl(self.fd, TIOCOUTQ, struct.pack("I", 0)))[0]
        except Exception:
            return -1

    def inq(self):
        try:
            return struct.unpack("I", fcntl.ioctl(self.fd, TIOCINQ, struct.pack("I", 0)))[0]
        except Exception:
            return -1

    def write_all(self, data, chunk=1024, timeout=10.0, flush_wait=True, gap=0.0):
        """完整写入：循环等待可写 + 分块写，直到全部送出（截断会导致固件卡死）"""
        n = 0
        t0 = time.time()
        while n < len(data):
            if time.time() - t0 > timeout:
                raise ScreenError("写入超时 %d/%d 字节（设备可能已卡死）" % (n, len(data)))
            _, w, _ = select.select([], [self.fd], [], 0.5)
            if not w:
                continue
            try:
                n += os.write(self.fd, data[n:n + chunk])
            except BlockingIOError:
                continue
            if gap:
                time.sleep(gap)
            if flush_wait:
                t1 = time.time()
                while self.outq() > 0 and time.time() - t1 < 2.0:
                    time.sleep(0.002)
        return n

    def read_all(self, timeout=0.5):
        buf = bytearray()
        end = time.time() + timeout
        while True:
            left = end - time.time()
            if left <= 0:
                break
            r, _, _ = select.select([self.fd], [], [], min(0.02, left))
            if r:
                try:
                    buf.extend(os.read(self.fd, 4096))
                except BlockingIOError:
                    pass
        return bytes(buf)

    def drain(self):
        try:
            termios.tcflush(self.fd, termios.TCIFLUSH)
        except Exception:
            pass

    def count_beats(self, seconds=1.0):
        return self.read_all(seconds).count(MSN_BEAT)

    def handshake(self, timeout=2.0):
        """握手：发 MSNCN 等回显（仅待机态有效）"""
        self.drain()
        self.write_all(MSN_HELLO, timeout=1.0, flush_wait=False)
        buf = bytearray()
        end = time.time() + timeout
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.02)
            if r:
                try:
                    buf.extend(os.read(self.fd, 4096))
                except BlockingIOError:
                    pass
                if MSN_HELLO in buf:
                    return True
        return False

    def wait_standby(self, timeout=5.0, need=6):
        """等待设备回到待机态（重新出现 10Hz 心跳）"""
        buf = bytearray()
        end = time.time() + timeout
        while time.time() < end:
            buf.extend(self.read_all(0.25))
            if buf.count(MSN_BEAT) >= need:
                self.display_mode = False
                return True
        return False

    def _transact(self, req, key, timeout=0.5, key_len=None):
        """发一条命令并等待包含 key 的响应（返回响应字节串或 None）"""
        self.drain()
        self.write_all(req, timeout=1.0, flush_wait=False)
        k = key
        klen = key_len or len(key)
        buf = bytearray()
        end = time.time() + timeout
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.01)
            if r:
                try:
                    buf.extend(os.read(self.fd, 4096))
                except BlockingIOError:
                    pass
                i = buf.find(k)
                if i >= 0 and len(buf) >= i + klen:
                    return bytes(buf[i:i + klen])
                if len(buf) > 128:
                    del buf[:-64]
        return None

    def read_adc(self, ch=9):
        """读 ADC 通道（按键）。仅待机态有效。"""
        resp = self._transact(bytes([8, ch, 0, 0, 0, 0]), bytes([8, ch]), timeout=0.6, key_len=6)
        if resp:
            return resp[4] * 256 + resp[5]
        return None

    def read_sfr_u8(self, addr):
        req = bytes([0, 48, 0, (addr >> 8) & 255, addr & 255, 0])
        resp = self._transact(req, req[:5], timeout=0.5, key_len=6)
        return resp[5] if resp else None

    def read_sfr_u16(self, addr):
        req = bytes([0, 48, 32, addr & 255, 0, 0])
        resp = self._transact(req, req[:4], timeout=0.5, key_len=6)
        return resp[4] * 256 + resp[5] if resp else None

    def read_size(self):
        """从设备寄存器读分辨率（待机态）"""
        w = self.read_sfr_u16(0x00)
        h = self.read_sfr_u16(0x01)
        if w and h:
            self.width, self.height = w, h
        return self.width, self.height

    def lcd_add(self, x=0, y=0, w=None, h=None, wait=True, timeout=2.0):
        """设置显示区域：只在进入页面时调用一次！"""
        w = w or self.width
        h = h or self.height
        pkt = (bytes([2, 0, (x >> 8) & 255, x & 255, (y >> 8) & 255, y & 255]) +
               bytes([2, 1, (w >> 8) & 255, w & 255, (h >> 8) & 255, h & 255]) +
               bytes([2, 3, 7, 0, 0, 0]))
        self.write_all(pkt, timeout=2.0, flush_wait=False)
        if not wait:
            return True
        buf = bytearray()
        end = time.time() + timeout
        while time.time() < end:
            r, _, _ = select.select([self.fd], [], [], 0.02)
            if r:
                try:
                    buf.extend(os.read(self.fd, 4096))
                except BlockingIOError:
                    pass
                if bytes([2, 3, 7]) in buf:
                    return True
        return False

    def lcd_state(self, direction=0):
        self.write_all(bytes([2, 3, 10, direction & 255, 0, 0]), timeout=1.0, flush_wait=False)
        return True

    def send_frame(self, payload):
        """发送一帧压缩数据（不含 LCD_ADD）"""
        self.write_all(payload, timeout=10.0, flush_wait=True)
        if len(payload) > 1024:
            time.sleep(0.1)          # 与 Windows 程序一致：大帧后排空
        self.display_mode = True
        return True

    def solid(self, rgb565):
        """整屏纯色（清屏/测试用）"""
        out = bytearray()
        fill = bytes([2, 4]) + bytes([(rgb565 >> 8) & 255, rgb565 & 255]) * 2
        for _ in range((self.width * self.height) // 128):
            out += fill + bytes([2, 3, 8, 1, 0, 0])
        return self.send_frame(bytes(out))

    def ensure_display(self, handshake=True):
        """确保处于显示态（待机态需要重新接管：握手 -> 设置方向 -> 设置区域）"""
        if self.display_mode:
            return True
        if handshake:
            self.handshake(timeout=1.5)
        # 方向必须每次都发（0=正向也是有效值！曾因跳过 0 导致"设回正向却没生效"）
        if self.direction is not None:
            self.lcd_state(self.direction)
            time.sleep(0.2)
        self.lcd_add(wait=True, timeout=1.5)
        self.log("已进入显示态（区域 %dx%d）" % (self.width, self.height))
        return True

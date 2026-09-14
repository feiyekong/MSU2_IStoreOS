#!/usr/bin/env python3
"""方向自检：依次把 0..7 号方向刷到屏幕上，每屏显示大号编号 + 方位标记

用法：cd /mnt/mmc1-4/msu2d/src && python3 ../tools/dir_test.py [每屏秒数]
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from msu2 import canvas as C          # noqa: E402
from msu2.transport import Screen     # noqa: E402

HOLD = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
NAMES = ["正向 (0°)", "反向 (180°)", "水平镜像", "垂直镜像",
         "顺时针90°", "逆时针90°", "水平镜像+90°", "垂直镜像+90°"]


def make_frame(d):
    cv = C.Canvas(160, 80)
    cv.clear(C.BLACK)
    # 边框（4 角不对称，便于判断旋转/镜像）
    cv.rect(0, 0, 160, 2, C.rgb(60, 60, 60))          # 上边
    cv.rect(0, 78, 160, 2, C.rgb(60, 60, 60))         # 下边
    # 左上角实心块 = 原点标记
    cv.rect(2, 2, 18, 12, C.RED)
    cv.text(3, 4, "TL", C.WHITE, 1)
    # 右上角文字
    cv.text(160 - cv.text_w("TR", 1) - 3, 4, "TR", C.rgb(0, 200, 255), 1)
    # 底部左/右文字
    cv.text(3, 68, "BL", C.rgb(0, 200, 255), 1)
    cv.text(160 - cv.text_w("BR", 1) - 3, 68, "BR", C.GREEN, 1)
    # 中间大号编号
    big = str(d)
    w = cv.text_w(big, 5)
    cv.text((160 - w) // 2, 22, big, C.YELLOW, 5)
    return cv


def show(d):
    scr = Screen(verbose=False, direction=d)
    scr.open()
    if scr.wait_standby(timeout=4.0):
        scr.handshake(timeout=1.5)
    scr.lcd_state(d)                      # 先设方向（待机态有效）
    time.sleep(0.25)
    scr.lcd_add(wait=True, timeout=1.5)
    cv = make_frame(d)
    scr.send_frame(cv.encode())
    return scr


def main():
    print("开始方向自检：每屏 %.1f 秒，共 8 屏（0..7）" % HOLD, flush=True)
    for d in range(8):
        scr = show(d)
        print("  方向 %d = %s 已显示" % (d, NAMES[d]), flush=True)
        time.sleep(HOLD)
        scr.close()                       # 关闭串口让设备回待机，下一屏重新接管
        time.sleep(0.8)
    # 收尾：回到正向
    scr = show(0)
    print("已恢复方向 0（正向）", flush=True)
    scr.close()


if __name__ == "__main__":
    main()

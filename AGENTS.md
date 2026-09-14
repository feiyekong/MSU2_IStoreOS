# AGENTS.md —— MSU2 USB 小屏幕（iStoreOS 移植项目）

本文件供在本项目工作的 AI 代理（Codex 等）建立上下文。
> **所有回复、注释、文档一律使用中文。**

---

## 1. 项目目标

把 Windows 桌面版「MSU2 USB 副屏工具」的能力迁移到 **iStoreOS 软路由**，由路由器直接驱动 USB 小屏显示：

- **实时网速**（WAN 上/下行）
- **CPU 温度**
- **内存占用**
- **CPU 占用率**
- 负载 / 运行时长等（可选）

- 上游参考实现（**只读，不要修改**）：E:/workSpace/MSU2_MINI_V2-5.10.0/MSU2_MINI_V2.py
- 移植产物目录（软路由）：/mnt/mmc1-4/msu2d/

---

## 2. 环境与访问

| 项 | 值 |
| --- | --- |
| SSH | MCP SSH default -> root@192.168.10.1:22 |
| 系统 | iStoreOS 25.12.5，内核 6.12.94，aarch64（Radxa E20C，4×A53，2 GB） |
| Python | /usr/bin/python3（3.13.9，**无 pip**） |
| 包管理 | apk |
| 屏幕节点 | /dev/ttyACM0（VID:PID = 1a86:fe0c，CH32x035） |
| 屏幕规格 | **160×80**，RGB565（已从设备寄存器 Lcd_X/Lcd_Y 确认） |
| 项目目录 | /mnt/mmc1-4/msu2d/ |
| WAN / LAN | pppoe-wan（物理口 eth1）/ br-lan |

---

## 3. 协议（已实测验证，务必按此实现）

### 3.1 初始化

```
打开串口：raw，115200，断言 DTR/RTS
握手：    00 4D 53 4E 43 4E (NUL+MSNCN)      -> 回显一致
进页面：   LCD_ADD(0,0,160,80) 只发一次：
           02 00 00 00 00 00 | 02 01 00 A0 00 50 | 02 03 07 00 00 00
           -> 回显 02 03 07 ... 表示区域就绪
SFR 读：   00 30 00 <addrH> <addrL> 00       -> 回显末字节为值
按键读：   08 09 00 00 00 00                 -> 08 09 00 00 <adcH> <adcL>（仅待机态可用）
设置方向： 02 03 0A <dir> 00 00
```

### 3.2 帧数据（压缩格式，照搬 Screen_Date_Process）

一帧 12800 像素，按 128 像素（256 字节）= 1 页，共 100 页：

```
cmp[k] = (pixel[2k] << 16) | pixel[2k+1]        # 64 个 uint32
bg     = 本页出现次数最多的 cmp 值
发送:  02 04 + 大端4字节(bg)                     # 设置本页底色
       对每个 cmp[k] != bg: 04 k + 大端4字节(cmp[k])
       02 03 08 01 00 00                         # 提交本页
```

- 大端拆字节：[(v>>24)&255,(v>>16)&255,(v>>8)&255,v&255]
- RGB565：((R&0xF8)<<8) | ((G&0xFC)<<3) | ((B&0xF8)>>3)
- 实测：纯色整屏帧 1,200 字节 / 0.105 秒；含动态条的帧 1.7–5.0 KB / 0.11–0.12 秒

### 3.3 设备行为（重要）

| 状态 | 表现 |
| --- | --- |
| 待机态 | 10Hz 发 00 4D 53 4E 30 31，所有指令都回显 |
| **显示态** | **心跳停止、指令不再回显（正常！）** |
| 显示态存活判断 | 写入是否被消费：TIOCOUTQ 归零、耗时正常 |
| 关闭串口 | 设备回到待机态 |
| 卡死 | TIOCOUTQ 长期不为 0 -> **只能物理断电恢复**（USB authorized 软复位无效） |

---

## 4. 开发铁律

1. **LCD_ADD 只在进入页面时发一次**，连续刷新时绝不再发（每帧重发会导致固件卡死，已实测）。
2. **一帧数据必须完整写出**（循环 select + 分段写直到全部送出）；写入被截断会导致解析错乱。
3. 在"等待像素数据"期间**不要插入其它类型命令**（读寄存器/读按键/切方向）。
4. 帧数据用 **1024 字节分块 + 等待 TIOCOUTQ 归零**（等效 pyserial flush()），大帧后 sleep(0.1)。
5. **串口独占**，进程常驻并保持串口打开（关闭后设备回待机，需重发 LCD_ADD 重新接管）。
6. **不写设备 Flash**（除非明确需要）。
7. **只用 Python 标准库**（os/termios/select/struct/time/json/collections）。
8. 不修改上游 MSU2_MINI_V2.py 等参考文件。

---

## 5. 指标数据源

| 指标 | 路径 |
| --- | --- |
| CPU 占用 | /proc/stat（两次采样求差，4 核） |
| CPU 温度 | /sys/class/thermal/thermal_zone0/temp（毫摄氏度） |
| 内存 | /proc/meminfo（MemTotal / MemAvailable） |
| 负载 | /proc/loadavg |
| 运行时长 | /proc/uptime |
| WAN 网速 | /sys/class/net/pppoe-wan/statistics/rx_bytes、tx_bytes |
| LAN 网速 | /sys/class/net/br-lan/statistics/rx_bytes、tx_bytes |
| 磁盘 I/O | /proc/diskstats |

---

## 6. 目录约定

```
forIstoreOS/                         # 仓库根目录；部署后为 /mnt/mmc1-4/msu2d/
├── README.md
├── AGENTS.md
├── LICENSE
├── docs/
│   ├── 操作手册.md
│   ├── 可行性方案.md
│   ├── 备份说明.md
│   └── images/
├── src/msu2/
│   ├── __init__.py
│   ├── transport.py
│   ├── canvas.py
│   ├── font.py
│   ├── metrics.py
│   ├── pages.py
│   └── main.py
├── etc/
│   ├── config/msu2
│   └── init.d/msu2d
├── luci/
│   ├── controller/msu2.lua
│   └── model/cbi/msu2/settings.lua
├── tools/
│   ├── install.sh
│   ├── install_luci.sh
│   ├── uninstall.sh
│   ├── preview.py
│   ├── dir_test.py
│   └── package.sh
└── dist/                             # 发布包/完整备份，不参与运行时
```

- transport.py：串口打开、完整写入、协议封包、待机/显示态管理、重连、ADC/SFR 读取
- canvas.py：RGB565 帧缓冲、图元/图标、压缩编码（3.2 节格式）；当前整帧编码，未实现脏页差分
- font.py：5×7 点阵字库（含度符号）
- metrics.py：/proc、/sys 数据采集与格式化
- pages.py：网速页、系统页、时钟页布局渲染
- main.py：CLI、主循环、页面轮播、状态文件
- LuCI/Lua：UCI 配置页、procd 服务、菜单注册
- 当前版本没有独立 keys.py；按键 ADC 仅由 `transport.read_adc()` 在待机态读取，尚未接入翻页交互

---

## 7. 常用排查命令（软路由上执行）

```bash
lsusb | grep -i ch32                     # 设备是否在
ls -l /dev/ttyACM0
cat /dev/ttyACM0 | hexdump -C            # 待机态应看到 10Hz 的 00 4D 53 4E 30 31
dmesg | tail -20                         # 插拔/异常
cat /sys/class/thermal/thermal_zone0/temp
cat /sys/class/net/pppoe-wan/statistics/rx_bytes
```

故障判断顺序：**设备在不在 -> 待机态心跳 -> 显示态看 TIOCOUTQ -> 卡死则物理断电**。

---

## 8. 已知坑（全部实际踩过）

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 发几帧后设备不再收数据 | 每帧重发 LCD_ADD | 只在进页面时发一次 |
| 设备完全不响应 | 帧数据被截断 / 中途插入其它命令 | 完整写入；帧中间不插入其它命令 |
| 显示态"没反应"以为坏了 | 显示态本来就不回显、不发心跳 | 用 TIOCOUTQ 判断 |
| 读 ADC 返回 None | 处于显示态 | 仅待机态读；或先停帧 |
| 重启后找不到 ttyACM0 | 节点名变化 | 按 VID/PID 扫描 / udev 规则 |
| 软复位无效 | authorized 只复位 USB 外设，MCU 主循环仍卡 | 物理断电 |

---

## 9. 页面与扩展

### 9.1 现有页面

| 页面 | 内容 | 源码 |
| --- | --- | --- |
| net（网速） | WAN 协商速率 + 下行/上行大字 + 上下行图标 + WAN 口 IP | pages.render_net |
| sys（系统） | CPU 占用 / CPU 温度 / 内存 + 进度条 + 运行时长 | pages.render_sys |
| clock（时钟） | 大号时间 + 秒 + **在线客户端数** + 日期星期 | pages.render_clock |

主程序参数：

```bash
python3 -m msu2.main --page auto     # 三页轮播（--rotate 每页秒数）
python3 -m msu2.main --page net|sys|clock
python3 -m msu2.main --frames N      # 跑 N 帧后退出（便于定时验证）
python3 -m msu2.main --once          # 只刷一帧
```

### 9.2 预览工具（改布局必备）

```bash
cd /mnt/mmc1-4/msu2d && python3 tools/preview.py --out /tmp/preview --scale 4
# 生成 page_net.png / page_sys.png / page_clock.png（4 倍放大，纯标准库无需 PIL）
```

改完布局先生成预览图确认，再刷到屏幕，避免反复折腾设备。

### 9.3 WAN 口 IP 与外网 IP（重要区别）

| 概念 | 取法 | 本例 |
| --- | --- | --- |
| **WAN 口 IP** | `metrics.iface_ip("pppoe-wan")`（ioctl 直读，零开销） | `100.102.91.192`（CGNAT 段 100.64/10） |
| **真实外网 IP** | 需请求外部服务（`metrics.public_ip()`，后台线程 10 分钟刷新一次） | `183.193.34.200` |

- 本页**默认显示 WAN 口 IP**（用户要求：直接看运营商给本机的地址，避免分不清真假）；
  若是 CGNAT 段会在右侧标 `NAT`。
- `public_ip()` 仍保留实现（可用外部服务拿到"世界看到的 IP"），需要时可在页面上另起一行显示。
- 判断 CGNAT：`metrics.is_cgnat(ip)`（100.64.0.0/10）。

### 9.4 在线客户端统计（已实现）

| 方法 | 说明 |
| --- | --- |
| `/proc/net/arp` 中 flags=0x2 | **推荐**：当前活跃设备（=在线客户端）。`Metrics.clients()` / `client_list()` |
| `/tmp/dhcp.leases` | 已分配地址（含已离线者），仅作参考。`dhcp_lease_count()` |
| `iwinfo <if> assoclist` / `ubus call hostapd.<if> get_clients` | 无线客户端（本机无射频，需指向下游 AP） |
| `ubus call dhcp ipv4leases` | **本固件不支持**（方法不存在） |
| nlbwmon | 未安装；装了才有"每设备实时流量" |

### 9.5 时钟时区（重要教训）

- 路由器时区已由 `uci system.@system[0].timezone` / `/etc/TZ`（本机为 `CST-8`）配置好，
  `time.localtime()` 已是北京时间。
- **禁止再手动加 +8 小时**（本项目的时钟页曾因此显示成晚上 9 点，实际是下午 1 点）。
- `render_clock(..., tz_offset=0)` 默认不使用偏移。

---

## 10. 调试速查

| 需求 | 命令 |
| --- | --- |
| 看设备是否待机 | `cat /dev/ttyACM0 \| hexdump -C`（应有 10Hz 心跳） |
| 看分辨率 | python3 -c 用 `Screen().read_size()`（读 SFR 0x00/0x01） |
| 看客户端 | `python3 -c "from msu2.metrics import Metrics; print(Metrics().client_list())"` |
| 单页预览 | `python3 tools/preview.py --out /tmp/p --scale 4` |
| 跑 60 帧 | `python3 -m msu2.main --frames 60 --interval 1` |

---

## 11. LuCI 网页控制模块（Lua）

菜单：**服务 → USB副屏 (MSU2)**　地址：`/cgi-bin/luci/admin/services/msu2`

| 文件 | 目标路径 | 作用 |
| --- | --- | --- |
| `luci/controller/msu2.lua` | `/usr/lib/lua/luci/controller/msu2.lua` | 注册菜单：`entry({"admin","services","msu2"}, cbi("msu2/settings"), _("USB副屏 (MSU2)"), 60)` |
| `luci/model/cbi/msu2/settings.lua` | `/usr/lib/lua/luci/model/cbi/msu2/settings.lua` | CBI 设置页（开关/页面/间隔/轮播/方向 + 状态 + 日志） |
| `etc/config/msu2` | `/etc/config/msu2` | UCI 配置 |
| `etc/init.d/msu2d` | `/etc/init.d/msu2d` | procd 服务（读 UCI → 启动 Python 主程序） |
| `tools/install_luci.sh` | — | 一键安装/修复以上全部（幂等） |

### 关键约定

- 本机 **已安装 `luci-compat`**，故采用经典 **Lua CBI** 方案（不是新版 JS 方案）。
- iStoreOS 自带模块（appfilter/cifs/linkease 等）同为 Lua 控制器，可参考。
- Python 主程序**直接解析** `/etc/config/msu2`（`main.load_uci_config()`），不调用 `uci` 命令。
- 配置字段：`enabled` / `page` / `interval` / `rotate` / `direction`(0..7)。
- 服务由 UCI 驱动：`enabled=0` 时 init 脚本不启动实例；网页"保存&应用"会 `restart` 服务。
- 屏幕方向（`direction`）必须在**待机态**、且在 `LCD_ADD` **之前**发送（见 `transport.ensure_display()`）。
- **开机自启默认关闭**：`/etc/init.d/msu2d enable` 才会写入 `/etc/rc.d`。
- 改完 Lua 文件后清缓存：`rm -rf /tmp/luci-*`，然后刷新浏览器。

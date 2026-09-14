#!/bin/sh
# MSU2 USB 小屏幕 —— 一键安装/升级脚本（OpenWrt / iStoreOS）
# 用法： sh install.sh [安装目录]      默认 /mnt/mmc1-4/msu2d
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
DEST=${1:-/mnt/mmc1-4/msu2d}
[ -d "$(dirname "$DEST")" ] || DEST=/opt/msu2d

echo "=== MSU2 副屏安装 ==="
echo "安装目录: $DEST"

# ---------- 1. 权限与依赖 ----------
[ "$(id -u)" = "0" ] || { echo "错误：请用 root 运行"; exit 1; }

if ! command -v python3 >/dev/null 2>&1; then
	echo "未检测到 python3，尝试安装 python3-light ..."
	if command -v apk >/dev/null 2>&1; then apk add python3-light || true
	elif command -v opkg >/dev/null 2>&1; then opkg update && opkg install python3-light || true
	fi
fi
command -v python3 >/dev/null 2>&1 || { echo "错误：python3 不可用，请先安装（apk add python3-light）"; exit 1; }
echo "python3: $(python3 -V 2>&1)"

HAVE_LUCI=0
[ -f /usr/lib/lua/luci/dispatcher.lua ] && HAVE_LUCI=1
[ $HAVE_LUCI = 1 ] || echo "提示：未检测到 LuCI Lua 运行时，将只安装命令行部分（可稍后装 luci-compat 再重跑本脚本）"

# ---------- 2. 复制程序文件 ----------
echo "[1/4] 复制程序到 $DEST"
mkdir -p "$DEST"
for d in src tools docs etc luci; do
	[ -d "$HERE/$d" ] && cp -r "$HERE/$d" "$DEST/" || true
done
[ -f "$HERE/AGENTS.md" ] && cp "$HERE/AGENTS.md" "$DEST/" || true
mkdir -p "$DEST/var"

# ---------- 3. 安装 /etc/config/msu2 ----------
echo "[2/4] 安装配置 /etc/config/msu2"
if [ ! -f /etc/config/msu2 ]; then
	cat > /etc/config/msu2 <<'UCI'
config msu2 'settings'
	option enabled '1'
	option page 'auto'
	option interval '1'
	option rotate '15'
	option direction '0'
UCI
else
	echo "      已存在，保留原配置"
fi

# ---------- 4. 安装 init 服务（路径按实际安装目录生成）----------
echo "[3/4] 安装服务 /etc/init.d/msu2d"
cat > /etc/init.d/msu2d <<INIT
#!/bin/sh /etc/rc.common
# MSU2 USB 小屏幕显示服务（由 LuCI 页面 /etc/config/msu2 控制）
START=95
STOP=10
USE_PROCD=1

SRC=$DEST/src
PY=/usr/bin/python3
[ -x "\$PY" ] || PY=\$(command -v python3)

start_service() {
	config_load msu2
	config_get enabled settings enabled 0
	if [ "\$enabled" != "1" ]; then
		logger -t msu2d "配置为禁用，不启动显示"
		return 0
	fi
	config_get page settings page auto
	config_get interval settings interval 1
	config_get rotate settings rotate 15
	config_get direction settings direction 0

	logger -t msu2d "启动显示 page=\$page interval=\$interval rotate=\$rotate direction=\$direction"

	procd_open_instance
	procd_set_param command "\$PY" -m msu2.main --page "\$page" --interval "\$interval" --rotate "\$rotate" --direction "\$direction" --quiet
	procd_set_param env PYTHONPATH="\$SRC"
	procd_set_param cwd "\$SRC"
	procd_set_param respawn 3600 5 5
	procd_set_param stdout 1
	procd_set_param stderr 1
	procd_close_instance
}

stop_service() {
	logger -t msu2d "停止显示"
}

service_triggers() {
	procd_add_reload_trigger "msu2"
}
INIT
chmod +x /etc/init.d/msu2d

# ---------- 5. 安装 LuCI 界面 ----------
if [ $HAVE_LUCI = 1 ]; then
	echo "[4/4] 安装 LuCI 页面（服务 -> USB副屏）"
	mkdir -p /usr/lib/lua/luci/controller /usr/lib/lua/luci/model/cbi/msu2
	cp "$DEST/luci/controller/msu2.lua" /usr/lib/lua/luci/controller/msu2.lua
	cp "$DEST/luci/model/cbi/msu2/settings.lua" /usr/lib/lua/luci/model/cbi/msu2/settings.lua
	rm -rf /tmp/luci-* 2>/dev/null || true
else
	echo "[4/4] 跳过 LuCI（无 Lua 运行时）"
fi

# ---------- 6. 启动并自检 ----------
echo "启动服务 ..."
/etc/init.d/msu2d restart >/dev/null 2>&1 || true
sleep 3

python3 -c "import sys; sys.path.insert(0,'$DEST/src'); import msu2.main" 2>/dev/null \
	&& echo "模块导入: OK" || echo "模块导入: 失败（请检查文件完整性）"

PID=$(ps | grep '[m]su2.main' | awk '{print $1}' | head -1)
if [ -n "$PID" ]; then
	echo "显示进程: 运行中 (PID $PID)"
else
	echo "显示进程: 未运行（若屏幕卡死请拔插一次 USB，然后执行 /etc/init.d/msu2d restart）"
fi

echo
echo "安装完成！"
echo "  网页控制: http://<路由器IP>/cgi-bin/luci/admin/services/msu2   （菜单：服务 -> USB副屏）"
echo "  开机自启: /etc/init.d/msu2d enable"
echo "  手动启动: /etc/init.d/msu2d restart"
echo "  查看手册: $DEST/docs/操作手册.md"

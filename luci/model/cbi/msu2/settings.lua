-- MSU2 USB 小屏幕：LuCI 设置页（服务 -> USB副屏）
local fs  = require "nixio.fs"
local sys = require "luci.sys"

local m = Map("msu2", translate("USB副屏 (MSU2)"),
	translate("160×80 USB 小屏显示控制：是否显示、显示哪一页、刷新频率、屏幕方向。"))

------------------------------------------------------------
-- 显示设置
------------------------------------------------------------
local s = m:section(NamedSection, "settings", "msu2", translate("显示设置"))
s.anonymous = true
s.addremove = false

local o = s:option(Flag, "enabled", translate("启用屏幕显示"),
	translate("关闭后停止出帧，屏幕恢复固件自带动画；开启后立即接管显示"))
o.rmempty = false
o.default = "1"

o = s:option(ListValue, "page", translate("显示页面"))
o:value("auto",  translate("自动轮播（网速 → 系统 → 时间）"))
o:value("net",   translate("仅网速（WAN 上下行）"))
o:value("sys",   translate("仅系统状态（CPU/温度/内存）"))
o:value("clock", translate("仅时间 + 在线客户端数"))
o.default = "auto"

o = s:option(Value, "interval", translate("刷新间隔（秒）"),
	translate("每次刷新之间等待的秒数，建议 1 秒"))
o.datatype = "range(0.2,60)"
o.default = "1"

o = s:option(Value, "rotate", translate("轮播每页停留（秒）"),
	translate("仅当页面选择“自动轮播”时生效"))
o.datatype = "range(3,3600)"
o.default = "15"

o = s:option(ListValue, "direction", translate("屏幕方向"),
	translate("屏幕倒装时选“反向 (180°)”；带 90° 的选项部分批次设备旋转顺序不同，可逐个试"))
o:value("0", translate("正向 (0°)"))
o:value("1", translate("反向 (180°)"))
o:value("2", translate("水平镜像"))
o:value("3", translate("垂直镜像"))
o:value("4", translate("顺时针 90°"))
o:value("5", translate("逆时针 90°"))
o:value("6", translate("水平镜像 + 90°"))
o:value("7", translate("垂直镜像 + 90°"))
o.default = "0"

local btn = s:option(Button, "_restart", translate("手动操作"))
btn.inputtitle = translate("立即重启显示进程")
btn.inputstyle = "apply"
btn.write = function()
	sys.call("/etc/init.d/msu2d restart >/dev/null 2>&1")
end

------------------------------------------------------------
-- 运行状态（读取守护进程写的 /tmp/msu2d.status，反映真实状态）
------------------------------------------------------------
local st = m:section(SimpleSection, translate("运行状态"))
st.anonymous = true

local dev_ok = fs.access("/dev/ttyACM0")
o = st:option(DummyValue, "_dev", translate("屏幕设备"))
o.rawhtml = true
o.value = dev_ok
	and "<span style='color:#2b8a3e;font-weight:bold'>已识别 /dev/ttyACM0</span>"
	or  "<span style='color:#c92a2a;font-weight:bold'>未识别设备（请检查 USB 连接）</span>"

local stt = {}
if fs.access("/tmp/msu2d.status") then
	local fh = io.open("/tmp/msu2d.status", "r")
	if fh then
		for line in fh:lines() do
			local k, v = line:match("^([%w_]+)=(.*)$")
			if k then stt[k] = v end
		end
		fh:close()
	end
end
local pid = tonumber(stt.pid) or 0
local alive = (pid > 0 and fs.access("/proc/" .. pid))

local page_names = { auto = "自动轮播", net = "网速", sys = "系统状态", clock = "时间+客户端" }
local dir_names = { ["0"]="正向", ["1"]="反向180°", ["2"]="水平镜像", ["3"]="垂直镜像",
                    ["4"]="顺时针90°", ["5"]="逆时针90°", ["6"]="镜像+90°", ["7"]="镜像+90°" }

o = st:option(DummyValue, "_svc", translate("显示进程"))
o.rawhtml = true
if alive then
	o.value = string.format(
		"<span style='color:#2b8a3e;font-weight:bold'>运行中</span>（PID %d）　页面：%s　刷新：%s 秒　方向：%s　已刷新 %s 帧／异常 %s 次",
		pid, page_names[stt.page] or stt.page or "-", stt.interval or "-",
		dir_names[stt.direction] or stt.direction or "-", stt.frames or "0", stt.errors or "0")
else
	o.value = "<span style='color:#868e96;font-weight:bold'>已停止</span>"
		.. "（保存并应用后会立即启动）"
end

o = st:option(DummyValue, "_cfg", translate("配置文件"))
o.rawhtml = true
o.value = "/etc/config/msu2　（命令：<code>uci show msu2</code>）"

------------------------------------------------------------
-- 最近日志
------------------------------------------------------------
local log = sys.exec("logread -e msu2d 2>/dev/null | tail -n 6")
if log and #log > 0 then
	log = log:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;")
	local lg = m:section(SimpleSection, translate("最近日志（msu2d）"))
	lg.anonymous = true
	o = lg:option(DummyValue, "_log", "")
	o.rawhtml = true
	o.value = "<pre style='white-space:pre-wrap;font-size:12px;background:#f8f9fa;padding:8px;border-radius:4px'>" .. log .. "</pre>"
end

------------------------------------------------------------
-- 保存后自动重启服务
------------------------------------------------------------
function m.on_after_commit(self)
	sys.call("/etc/init.d/msu2d restart >/dev/null 2>&1")
end

return m

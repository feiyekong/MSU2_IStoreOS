-- MSU2 USB 小屏幕：LuCI 菜单注册（服务 -> USB副屏）
module("luci.controller.msu2", package.seeall)

function index()
	entry({"admin", "services", "msu2"}, cbi("msu2/settings"), _("USB副屏 (MSU2)"), 60).dependent = true
end

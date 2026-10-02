# 映序局域网遥控调研

调研日期：2026-10-01。目标是让同一局域网中的手机通过浏览器控制桌面播放器；本文件是选型与实施建议，尚未实现该功能。

## 结论

**可行。** 建议在映序中增加一个用户主动开启的局域网 HTTP 服务，服务端同时提供手机控制页与同源 API。首版用短间隔拉取播放状态即可；若以后需要更即时的状态推送，再加 WebSocket。播放、暂停、进度、音量、上下集已有 `Playback` / `MainWindow` 方法与信号，主要工作在网络入口、身份验证、线程交接和手机界面。

**不要把 `PySide6.QtHttpServer` 当作默认实现。** 当前 `.venv` 的 PySide6 6.11.2 可以实际导入 `QHttpServer`、`QHttpServerConfiguration`，Qt for Python 也有[绑定文档](https://doc.qt.io/qtforpython-6/PySide6/QtHttpServer/index.html)和[示例](https://doc.qt.io/qtforpython-6/examples/example_httpserver_simplehttpserver.html)。但[Qt HTTP Server 官方许可](https://doc.qt.io/qt-6/qthttpserver-index.html#licenses)是 **GPLv3 或 Qt 商业许可**，没有 LGPL 选项；项目 `pyproject.toml` 当前声明 MIT，并通过 PyInstaller 发布 `.app`。MIT 源码本身可与 GPL 代码组合，但若选择社区版 Qt HTTP Server 分发组合程序，就需要按 GPLv3 的条件审视整个分发方式；仅在项目文件标 MIT 不足以免除该依赖的许可义务。这是选型限制，不是 Python 绑定缺失。若未来购买适用的 Qt 商业许可，可重评该模块。[Qt 总许可说明](https://doc.qt.io/qt-6/licensing.html)、[GNU GPL FAQ](https://www.gnu.org/licenses/gpl-faq.html)。

## 技术选型

| 方案 | 能力与集成 | 对本项目的判断 |
| --- | --- | --- |
| `aiohttp.web` | 单个 Python 服务同时提供静态 HTML、JSON API 与 WebSocket；项目官方仓库标识 [Apache-2.0](https://github.com/aio-libs/aiohttp)，[服务端文档](https://docs.aiohttp.org/en/stable/web.html)涵盖路由、WebSocket、`AppRunner`。 | **首选**。新增一个依赖，运行于独立 asyncio 线程；通过 Qt 信号把控制命令送回 GUI 线程。Apache-2.0 不要求映序自身改成 GPL。 |
| `QWebSocketServer` | [PySide6 已提供绑定](https://doc.qt.io/qtforpython-6/PySide6/QtWebSockets/QWebSocketServer.html)，与 Qt 主事件循环天然集成；[Qt WebSockets 为 LGPLv3 或 GPLv2／商业许可](https://doc.qt.io/qt-6/qtwebsockets-index.html#licenses)。本地 PySide6 6.11.2 导入成功。 | 可用于第二阶段双向通信，但它是 WebSocket 服务器，仍需另外提供手机网页的 HTTP 服务；首版只为遥控加 WebSocket 会增加协议与部署面。 |
| `QHttpServer` | [路由、响应与绑定 `QTcpServer`](https://doc.qt.io/qt-6/qthttpserver-index.html)很适合嵌入 Qt；Qt 提醒其面向可信网络，不应直接暴露到互联网。 | 技术上合适，但 GPLv3／商业许可与目前 MIT 发布策略冲突；不推荐。 |
| Python 标准库 `http.server` | 无额外依赖。 | [Python 官方明确说不建议生产使用，只做基础安全检查](https://docs.python.org/3/library/http.server.html)；不适合默认开放局域网的正式功能。 |

`pyproject.toml` 目前写的是 `PySide6>=6.7`，并未锁定 6.11.2。即使重新考虑 Qt HTTP Server，也要按项目所允许的**最低版本**核实 API：例如[部分 `QHttpServerConfiguration` 安全选项从 Qt 6.10／6.11 才加入](https://doc.qt.io/qt-6/qthttpserver-security.html)。不要依据开发机当前版本直接使用新 API。

## 推荐结构和首版范围

1. 应用菜单或设置中提供“开启局域网遥控”，默认关闭。开启时只绑定选定的本机私有网络接口与一个端口；停止、退出或切换网络时关闭监听。Qt 的 [`QTcpServer.listen`](https://doc.qt.io/qtforpython-6/PySide6/QtNetwork/QTcpServer.html)文档说明 `Any` 会监听全部网络接口，因此不可把 `0.0.0.0` 当成“仅局域网”的安全边界。`aiohttp` 同理应指定实际接口 IP。
2. 服务端提供 `/` 控制页、`GET /api/state`、少量显式的控制命令端点。网页与 API 使用同一个 scheme/host/port，避免额外的跨源配置；浏览器 `fetch` 默认受[同源策略和 CORS](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CORS)约束。首版状态可约 1 秒拉取；交互后立即刷新。
3. 网络线程只解析与验证请求，不直接触碰 `MainWindow`、`Playback` 或其他 GUI 对象。将允许的命令封装成 Qt 信号／排队调用，在 GUI 线程执行；再以受控的状态快照回传网络线程。现有 `Playback` 已暴露 `play`、`pause`、`seek_absolute`、`set_volume` 与状态信号；`MainWindow` 已有上下集、循环模式等路径。限制允许的命令，不提供任意文件路径、shell 或下载接口。
4. 手机页首版只做播放／暂停、前后跳、进度、音量、上一集／下一集、当前标题和播放状态。文件打开、字幕导出等读取本机文件的功能不纳入首版，减少远程访问面。
5. 桌面显示可扫描的二维码和可复制 URL，例如 `http://192.168.x.y:端口/`。二维码只是传递网址，不负责鉴权；首次访问仍需要在桌面确认或输入一次性配对码。若网络 IP 改变，应更新地址和二维码。Bonjour 可作为后续的自动发现增强；[Apple 说明 Bonjour 用于局域网服务发布和发现](https://developer.apple.com/bonjour/index.html)，首版无需依赖它。

## 安全边界

- **必须配对**：局域网中任意设备都可能尝试连接。建议生成短期、一次性配对码，在桌面显示并限速尝试；配对后给浏览器一个随机会话凭据，支持撤销与服务关闭时失效。二维码里只放服务地址，不放长期控制密钥。对所有状态与控制 API 做身份验证；`Origin`、`Host` 与请求体均需校验，命令参数设范围与大小上限。
- **跨站请求**：CORS 不等于鉴权，跨源表单提交等写操作仍可能发生；[MDN 同源策略](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Same-origin_policy)说明跨源写入通常是允许的。控制命令使用 POST、验证会话与 `Origin`、避免开放 `Access-Control-Allow-Origin: *`。若加 WebSocket，[RFC 6455 要求服务器审查预期的 `Origin`](https://www.rfc-editor.org/rfc/rfc6455#section-10.2)，但非浏览器客户端能伪造它，仍要独立鉴权。
- **明文局域网**：普通 `http://`／`ws://` 没有传输加密，适用于用户信任的家庭局域网；不应宣称能防止同网段监听或恶意设备。公共 Wi-Fi、访客网、端口转发及公网暴露不属于首版支持场景。若要覆盖不可信网络，需要 HTTPS／WSS 与可靠证书分发。Qt 自己也明确[轻量 HTTP Server 不应直面互联网](https://doc.qt.io/qt-6/qthttpserver-index.html#limitations-and-security)。
- **浏览器环境**：从手机直接打开映序提供的 `http://本机私有IP:端口/`，同源页面可正常请求同源 API。不要把控制页放在一个 HTTPS 公网站点，再让它跨源访问本机 HTTP 服务；浏览器对此有[混合内容、同源及本地网络访问限制](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Local_network_access)。私有 IP 上的 HTTP 也不享有 `localhost` 那样的[安全上下文待遇](https://developer.mozilla.org/en-US/docs/Web/Security/Secure_Contexts)，首版不要依赖仅限安全上下文的浏览器能力。

## macOS 与发布

- macOS 15 起有[本地网络隐私权限](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy)。Apple 要求使用局域网的 app 在 `Info.plist` 提供 `NSLocalNetworkUsageDescription`；若注册／浏览特定 Bonjour 服务，再列出 `NSBonjourServices`。若只显示 IP 和二维码，则不必为了发现功能添加 Bonjour 服务类型。Apple 指出从 Terminal 启动的命令行程序及子进程可能自动获准，而普通 `.app` 需按权限流程处理；因此须测试打包的 `.app`，不能只测源码运行。
- macOS [防火墙可以阻止传入连接](https://support.apple.com/guide/security/firewall-security-in-macos-seca0e83763f/web)。未加入允许列表的 app 可能弹出允许／拒绝提示；[Apple 用户指南](https://support.apple.com/guide/mac-help/mh34041/mac)说明用户决定前连接会被拒绝。现有 README 说明下载版尚未 Developer ID 签名和公证，这会使防火墙与本地网络权限体验更需实机验证；Apple 也[建议以 Apple 颁发的证书签名来稳定识别 macOS 本地网络权限主体](https://developer.apple.com/documentation/technotes/tn3179-understanding-local-network-privacy)。
- 当前 `packaging/player.spec` 的 `BUNDLE(info_plist=...)` 尚无局域网用途说明；实施时需要补充并确认 PyInstaller 收集新依赖、网页资源及其许可证文件。不要直接让 HTTP 服务把整个项目目录或用户媒体目录当成静态目录。

## 验证重点

从源码运行与实际 `.app` 各测一次；手机与 Mac 位于同一 Wi-Fi 时扫码、配对和控制；本机 IP 变化、Wi-Fi 断开、睡眠恢复后地址刷新；拒绝本地网络权限与防火墙入站权限时给出可操作错误；未配对、过期、跨站请求与错误参数都不能执行命令；关闭遥控后端口立即不再监听。访客网络的客户端隔离、VPN 或路由器规则可能阻断设备互访，这类失败应明确提示检查同网段可达性。

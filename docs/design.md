# 设计说明

## 目标

简洁实用的 macOS 桌面播放器（架构保持跨平台兼容），三个核心特性：

1. **本地 AI 实时生成字幕**（不联网、不上传数据）
2. **当前目录文件自动生成播放列表**
3. **自动跳过片尾**（可开关）

## 技术选型

| 组件 | 选型 | 理由 |
|---|---|---|
| UI | PySide6 (Qt 6) | 工作区 Python 生态；控件成熟 |
| 播放内核 | libmpv（python-mpv 绑定） | MKV 生态事实标准（IINA 同源）：HEVC/AV1/10bit、多音轨、ASS 内封字幕、VideoToolbox 硬解开箱即用 |
| 音频解码 | PyAV | 独立解码 16kHz mono PCM 供转写，与播放管线解耦（静音播放也能出字幕） |
| 语音识别 | faster-whisper (int8) | Apple Silicon CPU 快于实时；STT 接口可替换（如 sherpa-onnx/SenseVoice） |
| 持久化 | JSON（原子写入） | 设置、进度、片尾标记；字幕缓存为 .srt |

## 架构

```
ui/  main_window ── 组装层，全部交互与生命周期
       │
core/ playback ──── libmpv 适配层（属性观察 → Qt 信号，跨线程封送）
      playlist ──── 目录扫描/自然排序/循环模式（纯逻辑）
      settings/store ─ JSON 持久化（纯逻辑）
ai/  transcriber ── 领先播放进度的转写调度（后台线程）
      audio_source  PyAV 分块解码（可 seek，线程安全关闭）
      subtitles ──── 分段存储 + 区间覆盖跟踪 + SRT 缓存/导出
      whisper_backend STT 实现（模型懒加载 + 下载进度回调）
      skip ───────── 片尾跳过状态机
```

依赖方向：`ui → core + ai`，`ai → base 抽象`，core/ai 均不依赖 Qt（ai 完全纯 Python，core 仅 playback 依赖 Qt 信号）。

## 关键设计决策

### AI 字幕为何是"领先转写"而非逐句流式

whisper 类模型不是流式模型，逐句 hack 有 3–10s 固定延迟且易幻觉。改为：
转写线程持续把**播放位置之后 60 秒窗口**内的未转写区间转写掉，字幕按时钟
精确显示——观感即"实时"，且结果可整体缓存、可断点续转、seek 后自动重定锚。
领先窗口无欠账后，后台补全整个文件，完成即写 .srt 缓存（指纹 = 路径+大小+mtime），
二次打开零开销。

边界处理：每个 30s 窗口多解码 2s 前置上下文提升断句质量，结果中丢弃落在上下文
区的分段；单窗口失败标记该区间已覆盖并提示，避免死循环阻塞。

### 字幕源策略（MKV 场景）

- **自动**（默认）：文件有内置字幕轨（含 ASS）→ mpv 渲染，AI 不启动；没有 → AI
- **始终启用**：隐藏内置字幕轨（`sid=no`），AI 叠层接管，避免双字幕重叠
- **关闭**：只用内置字幕

### 渲染

QOpenGLWidget + mpv render API（`vo=libmpv`）。macOS 默认 GL 2.1 兼容上下文
会导致 mpv 禁用缩放器与 VideoToolbox 硬解互操作，故启动时显式请求
**GL 3.3 Core**（`QSurfaceFormat`）。mpv 更新回调来自其内部线程，经 Qt 信号
排队回 GUI 线程；GL 调用只在 initializeGL/paintGL。

### 片尾跳过

MVP 采用"人工标记 + 两级记忆"：标记一次写入单文件与同目录两条记录
（同季剧标一集全目录生效），文件级优先于目录级；全局开关默认关。
进入标记点后 90 秒宽限窗口内触发一次跳转（容忍 seek 抖动）。
自动检测（黑场/静音统计）留作后续增强，接口已在 skip.py 预留。

### 线程模型

- GUI 线程：Qt 事件循环、所有 UI 更新
- mpv 事件线程：属性观察回调 → 只发 Qt 信号
- 转写线程：AudioDecoder + STTBackend，进度经回调 → Qt 信号
- AudioDecoder 内部加锁：调度器 stop 与工作线程解码不竞态

## 已知取舍

- 进度记忆仅保留最近 500 条（LRU 近似）
- 转写 `beam_size=1`、`condition_on_previous_text=False`：速度优先、避免跨块幻觉
- 音轨/字幕轨切换通过菜单（文件加载后动态重建）
- 打包用 PyInstaller，libmpv.dylib 随 .app 捆绑，消除 brew 运行时依赖

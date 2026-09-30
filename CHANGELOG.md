# Changelog

本项目的所有重要变更将记录在此文件中。格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [Unreleased]

### Added

- **播放内核**：libmpv（`vo=libmpv` + render API 嵌入 QOpenGLWidget，GL 3.3 Core 保住缩放器与 VideoToolbox 硬解）；MKV 多音轨/内封字幕开箱即用，菜单可切换轨道。
- **目录自动播放列表**：打开任一文件自动扫描同目录媒体文件（视频+音频扩展名），自然排序（EP2 < EP10，同 stem 时 mkv 优先），支持单曲循环/列表循环/随机，侧栏面板可收起。
- **本地 AI 实时字幕**：faster-whisper（默认 small/int8）+ PyAV 独立解码；转写线程领先播放位置 60 秒滚动生成，观感实时；结果按文件指纹缓存 .srt，二次打开秒载；支持导出、模型大小（tiny/base/small/medium）与语言设置；首次使用自动下载模型并显示进度。
- **字幕源策略**：自动（内置字幕优先）/ 始终 AI / 关闭，三档可切。
- **自动跳过片尾**：手动标记一次，单文件 + 同目录两级记忆；全局开关默认关；手动跳过按钮兜底。
- **播放体验**：拖拽打开、续播记忆（单文件进度）、音量/倍速、空格/方向键快捷键、深色主题、窗口状态记忆。
- **打包**：PyInstaller spec 捆绑 libmpv.dylib，产出独立 Player.app。
- **工程设施**：Makefile（setup/lint/format/test/run/package）、pytest（core/ai 单测 + pytest-qt 离屏冒烟）、ruff/black/isort、真机冒烟脚本（渲染截图 / AI 链路）。

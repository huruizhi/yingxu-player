"""pytest-qt 公共配置：UI 测试默认离屏运行。"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

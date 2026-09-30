"""The idle screen offers a direct route into playback."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from player.ui.icons import icon
from player.ui.theme import OVERLAY_QSS


class EmptyState(QWidget):
    open_file = Signal()
    open_directory = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("emptyState")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(OVERLAY_QSS)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 28, 28, 28)
        layout.setSpacing(0)
        layout.addStretch(3)

        mark = QLabel()
        mark.setObjectName("emptyMark")
        mark.setAlignment(Qt.AlignCenter)
        mark.setFixedSize(96, 96)
        mark.setPixmap(icon("play", "#e5e9f0", 52).pixmap(52, 52))
        layout.addWidget(mark, 0, Qt.AlignCenter)
        layout.addSpacing(22)
        title = QLabel("准备好开始播放了吗？")
        title.setObjectName("welcomeTitle")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)
        layout.addSpacing(12)
        description = QLabel("拖入视频或音频，开始播放")
        description.setObjectName("welcomeDescription")
        description.setAlignment(Qt.AlignCenter)
        layout.addWidget(description)
        layout.addSpacing(30)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        actions.addStretch()
        self.open_btn = QPushButton("打开文件")
        self.open_btn.setObjectName("openPrimary")
        self.open_btn.setIcon(icon("open", "#1b263a").pixmap(18, 18))
        self.open_btn.setCursor(Qt.PointingHandCursor)
        self.open_btn.clicked.connect(self.open_file.emit)
        self.folder_btn = QPushButton("打开目录")
        self.folder_btn.setObjectName("openSecondary")
        self.folder_btn.setCursor(Qt.PointingHandCursor)
        self.folder_btn.clicked.connect(self.open_directory.emit)
        actions.addWidget(self.open_btn)
        actions.addWidget(self.folder_btn)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addSpacing(18)
        hint = QLabel("⌘ O  打开文件     ·     ⇧ ⌘ O  打开目录")
        hint.setObjectName("welcomeHint")
        hint.setAlignment(Qt.AlignCenter)
        layout.addWidget(hint)
        layout.addStretch(4)
        formats = QLabel("支持常见视频与音频格式")
        formats.setObjectName("welcomeHint")
        formats.setAlignment(Qt.AlignCenter)
        layout.addWidget(formats)

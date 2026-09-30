"""Single-instance handoff for app launches and media-open requests."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from PySide6.QtCore import QLockFile, QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    """Own a local server or forward launches to the running app."""

    request_received = Signal(object)

    def __init__(self, server_name: str) -> None:
        super().__init__()
        self.server_name = server_name
        self.server = QLocalServer(self)
        self._buffers: dict[QLocalSocket, bytearray] = {}
        lock_path = Path(tempfile.gettempdir()) / f"{server_name}.lock"
        self._lock = QLockFile(str(lock_path))
        self.is_primary = self._lock.tryLock(0)
        if self.is_primary:
            # The process lock makes it safe to remove a stale socket after a crash.
            QLocalServer.removeServer(server_name)
            self.is_primary = self.server.listen(server_name)
            if not self.is_primary:
                self._lock.unlock()
        if self.is_primary:
            self.server.newConnection.connect(self._accept_connections)

    def forward(self, media_path: str | None) -> bool:
        """Ask the primary process to activate and optionally open media."""
        socket = QLocalSocket()
        socket.connectToServer(self.server_name)
        if not socket.waitForConnected(500):
            return False

        payload = json.dumps(media_path, ensure_ascii=False).encode("utf-8") + b"\n"
        socket.write(payload)
        sent = socket.waitForBytesWritten(500)
        socket.disconnectFromServer()
        return sent

    def _accept_connections(self) -> None:
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            if socket is None:
                continue
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(lambda connection=socket: self._read_request(connection))
            socket.disconnected.connect(lambda connection=socket: self._drop_connection(connection))
            self._read_request(socket)

    def _read_request(self, socket: QLocalSocket) -> None:
        buffer = self._buffers.get(socket)
        if buffer is None:
            return
        buffer.extend(bytes(socket.readAll()))
        if b"\n" not in buffer:
            return
        line, _, _ = buffer.partition(b"\n")
        try:
            media_path = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            media_path = None
        if media_path is None or isinstance(media_path, str):
            self.request_received.emit(media_path)
        socket.disconnectFromServer()

    def _drop_connection(self, socket: QLocalSocket) -> None:
        self._buffers.pop(socket, None)

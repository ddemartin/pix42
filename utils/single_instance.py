"""Single-instance enforcement via QLocalServer / QLocalSocket."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    """
    Ensures only one Luma process acts as the 'primary' window.

    Usage
    -----
    si = SingleInstance()
    if si.try_become_primary():
        # this is the first instance — start the app normally
        si.file_open_requested.connect(window.open_path_str)
    else:
        # another instance is running — forward the path and exit
        si.send_to_primary(path_str)
        sys.exit(0)
    """

    file_open_requested = Signal(str)

    PIPE_NAME = "LumaViewer"

    # ------------------------------------------------------------------ #

    def try_become_primary(self) -> bool:
        """
        Attempt to claim the named server.

        Returns True if this process is now the primary instance.
        Probes for a live server first; only removes the socket file if
        no one is listening (stale crash remnant), so an already-running
        instance is never evicted.
        """
        probe = QLocalSocket()
        probe.connectToServer(self.PIPE_NAME)
        if probe.waitForConnected(500):
            probe.disconnectFromServer()
            return False  # a live primary instance already exists

        probe.abort()

        self._server = QLocalServer(self)
        QLocalServer.removeServer(self.PIPE_NAME)  # clean up stale socket
        ok = self._server.listen(self.PIPE_NAME)
        if ok:
            self._server.newConnection.connect(self._on_connection)
        return ok

    def send_to_primary(self, path: str) -> bool:
        """
        Send *path* to the already-running primary instance.

        Returns True if the message was delivered.
        """
        sock = QLocalSocket()
        sock.connectToServer(self.PIPE_NAME)
        if not sock.waitForConnected(1000):
            return False
        sock.write(path.encode("utf-8"))
        sock.flush()
        sock.waitForBytesWritten(500)
        sock.disconnectFromServer()
        return True

    # ------------------------------------------------------------------ #
    # Private                                                              #
    # ------------------------------------------------------------------ #

    def _on_connection(self) -> None:
        conn = self._server.nextPendingConnection()
        conn.readyRead.connect(lambda: self._read(conn))

    def _read(self, conn: QLocalSocket) -> None:
        data = conn.readAll().data().decode("utf-8", errors="replace").strip()
        if data:
            self.file_open_requested.emit(data)
        conn.close()

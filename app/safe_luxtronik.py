"""One Luxtronik TCP session at a time, always finished cleanly.

luxtronik 0.3.14 connects inside read() and closes only after parameters,
calculations, and visibilities all succeed. A timeout skips that close, and the
controller accepts a single client on the data port.

A second failure mode remains in that library. recv(4) may return fewer than
four bytes. The library drops that fragment and keeps going, so the rest of the
reply stays unread. close() then aborts the TCP session. This firmware treats
that abort as a live client and waits on its watchdog from then on.
"""

import logging
import socket
import struct
import threading

from luxtronik import Luxtronik
from luxtronik.calculations import Calculations
from luxtronik.parameters import Parameters
from luxtronik.visibilities import Visibilities

logger = logging.getLogger("luxtronik_advisor")

# Long enough for a LAN read, short enough that a lost packet cannot pin the controller.
SOCKET_TIMEOUT_SECONDS = 4.0

# After a failed read, wait this long for the rest of the reply to arrive
# before giving up and closing. A finished read does not wait.
DRAIN_IDLE_SECONDS = 0.5
DRAIN_BYTE_CAP = 512 * 1024

# A real parameter block is about 1100 values. Anything larger is a lost frame.
MAX_BLOCK_ITEMS = 10000

# The poller and the API share this. RLock so a settings write can read, write,
# and read back without letting another thread open a second socket in between.
controller_lock = threading.RLock()


class _ExactSocket:
    """recv(n) returns n bytes, or raises. It never returns a short fragment."""

    def __init__(self, raw: socket.socket):
        self.raw = raw

    def recv(self, count: int) -> bytes:
        pending = bytearray()
        while len(pending) < count:
            chunk = self.raw.recv(count - len(pending))
            if not chunk:
                raise ConnectionError("Luxtronik closed the connection")
            pending += chunk
        return bytes(pending)

    def sendall(self, data: bytes) -> None:
        self.raw.sendall(data)

    def settimeout(self, value: float | None) -> None:
        self.raw.settimeout(value)

    def shutdown(self, how: int) -> None:
        self.raw.shutdown(how)

    def close(self) -> None:
        self.raw.close()


class SafeLuxtronik(Luxtronik):
    """Luxtronik 0.3.14 that does not read in __init__ and always shuts the socket."""

    def __init__(self, host: str, port: int, safe: bool = True):
        # Luxtronik.__init__ calls read(), which downloads every register.
        self._host = host
        self._port = port
        self._socket = None
        self._raw: socket.socket | None = None
        self.calculations = Calculations()
        self.parameters = Parameters(safe=safe)
        self.visibilities = Visibilities()

    def _connect(self):
        self._force_close()
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Stored before connect() so a refused connection is still closed.
        self._raw = raw
        self._socket = _ExactSocket(raw)
        raw.settimeout(SOCKET_TIMEOUT_SECONDS)
        raw.connect((self._host, self._port))

    def _disconnect(self):
        self._force_close()

    def disconnect(self):
        self._force_close()

    def _force_close(self, *, drain: bool = False):
        """Send FIN. Read any leftover first so the kernel does not send RST."""
        raw = self._raw
        if raw is None and isinstance(self._socket, _ExactSocket):
            raw = self._socket.raw
        elif raw is None:
            raw = self._socket
        self._raw = None
        self._socket = None
        if raw is None:
            return
        try:
            # SHUT_WR finishes the session. SHUT_RDWR aborts it, and this
            # controller then sits in its watchdog loop.
            raw.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        try:
            _discard_pending(raw, wait=drain)
        except Exception:
            logger.debug("Could not drain the Luxtronik socket", exc_info=True)
        try:
            raw.close()
        except OSError:
            pass

    def _read_int(self) -> int:
        if self._socket is None:
            raise ConnectionError("Luxtronik socket is closed")
        return struct.unpack(">i", self._socket.recv(4))[0]

    def _read_block(self, command: int, item_size: int, label: str, *, with_status: bool) -> list[int]:
        if self._socket is None:
            raise ConnectionError("Luxtronik socket is closed")
        self._socket.sendall(struct.pack(">ii", command, 0))
        self._read_int()
        if with_status:
            self._read_int()
        length = self._read_int()
        if length < 0 or length > MAX_BLOCK_ITEMS:
            raise ConnectionError(f"Luxtronik {label} length {length} is not usable")
        if item_size == 1:
            return [struct.unpack(">b", self._socket.recv(1))[0] for _ in range(length)]
        return [self._read_int() for _ in range(length)]

    def _exchange(self, read) -> None:
        finished = False
        with controller_lock:
            try:
                self._connect()
                read()
                finished = True
            finally:
                self._force_close(drain=not finished)

    def read_calculations_only(self) -> None:
        """Command 3004. The five-minute poll needs nothing else."""
        self._exchange(self._read_calculations)

    def read_parameters_only(self) -> None:
        """Command 3003. Household settings live in the parameter block."""
        self._exchange(self._read_parameters)

    def read(self) -> None:
        """Parameters, calculations, and visibilities. Used by the information page."""

        def _all() -> None:
            self._read_parameters()
            self._read_calculations()
            self._read_visibilities()

        self._exchange(_all)

    def _read_parameters(self):
        self.parameters.parse(self._read_block(3003, 4, "parameters", with_status=False))

    def _read_calculations(self):
        self.calculations.parse(self._read_block(3004, 4, "calculations", with_status=True))

    def _read_visibilities(self):
        self.visibilities.parse(self._read_block(3005, 1, "visibilities", with_status=False))

    def write(self) -> None:
        finished = False
        with controller_lock:
            try:
                super().write()
                finished = True
            finally:
                self._force_close(drain=not finished)


def _recv_available(raw: socket.socket, total: int) -> int:
    """Read bytes already queued. Does not wait for the controller."""
    raw.settimeout(0)
    while total < DRAIN_BYTE_CAP:
        try:
            chunk = raw.recv(4096)
        except BlockingIOError:
            return total
        except OSError:
            return total
        if not chunk:
            return total
        total += len(chunk)
    return total


def _discard_pending(raw: socket.socket, *, wait: bool) -> None:
    """Empty the receive buffer. close() sends RST when it is not empty."""
    total = _recv_available(raw, 0)
    if wait and total < DRAIN_BYTE_CAP:
        # The rest of a failed reply may still be on the wire.
        raw.settimeout(DRAIN_IDLE_SECONDS)
        while total < DRAIN_BYTE_CAP:
            try:
                chunk = raw.recv(4096)
            except OSError:
                break
            if not chunk:
                break
            total += len(chunk)
    if total:
        logger.warning(
            "Discarded %s unread Luxtronik bytes so the controller sees a clean close",
            total,
        )

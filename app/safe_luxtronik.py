"""One Luxtronik TCP session at a time, always closed.

luxtronik 0.3.14 connects inside read() and closes only after parameters,
calculations, and visibilities all succeed. A timeout skips that close, and the
controller accepts a single client on the data port.
"""

import logging
import socket
import threading

from luxtronik import Luxtronik
from luxtronik.calculations import Calculations
from luxtronik.parameters import Parameters
from luxtronik.visibilities import Visibilities

logger = logging.getLogger("luxtronik_advisor")

# Long enough for a LAN read, short enough that a lost packet cannot pin the controller.
SOCKET_TIMEOUT_SECONDS = 4.0

# The poller and the API share this. RLock so a settings write can read, write,
# and read back without letting another thread open a second socket in between.
controller_lock = threading.RLock()


class SafeLuxtronik(Luxtronik):
    """Luxtronik 0.3.14 that does not read in __init__ and always shuts the socket."""

    def __init__(self, host: str, port: int, safe: bool = True):
        # Luxtronik.__init__ calls read(), which downloads every register.
        self._host = host
        self._port = port
        self._socket = None
        self.calculations = Calculations()
        self.parameters = Parameters(safe=safe)
        self.visibilities = Visibilities()

    def _connect(self):
        self._force_close()
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(SOCKET_TIMEOUT_SECONDS)
        self._socket.connect((self._host, self._port))

    def _disconnect(self):
        self._force_close()

    def disconnect(self):
        self._force_close()

    def _force_close(self):
        sock = self._socket
        self._socket = None
        if sock is None:
            return
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass

    def _exchange(self, read) -> None:
        with controller_lock:
            try:
                self._connect()
                read()
            finally:
                self._force_close()

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

    def write(self) -> None:
        with controller_lock:
            try:
                super().write()
            finally:
                self._force_close()

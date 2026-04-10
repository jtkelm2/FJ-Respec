"""Reproduces a bug in TCPConnection.recv():

It buffers chunks until a newline appears, then returns only the first line
and discards the remainder of the buffer. If two messages arrive in a single
TCP read, the second message is silently dropped.
"""

import socket
import pytest
from interact.connection import TCPConnection


def test_recv_drops_subsequent_messages_in_same_chunk():
    """Two complete JSON messages in one TCP read — only the first is returned;
    the second is silently lost."""
    a, b = socket.socketpair()
    try:
        # Write both messages in one syscall, guaranteeing they land
        # in b's receive buffer together.
        a.sendall(b'{"type": "msg1"}\n{"type": "msg2"}\n')

        # Confirm both bytes are present in b's buffer before we touch TCPConnection
        peek = b.recv(4096, socket.MSG_PEEK)
        assert b'"msg1"' in peek
        assert b'"msg2"' in peek

        b.settimeout(1.0)  # don't hang forever if recv() blocks
        conn = TCPConnection(b)

        msg1 = conn.recv()
        assert msg1 == {"type": "msg1"}

        # If the bug is real, the second recv() will time out (msg2 was discarded
        # along with the rest of the buffer after the first newline).
        try:
            msg2 = conn.recv()
        except (socket.timeout, TimeoutError) as e:
            pytest.fail(
                f"BUG REPRODUCED: second recv() blocked indefinitely. "
                f"msg2 was silently dropped from the receive buffer. "
                f"Exception: {type(e).__name__}: {e}"
            )

        assert msg2 == {"type": "msg2"}, f"got {msg2}"
    finally:
        a.close()
        b.close()

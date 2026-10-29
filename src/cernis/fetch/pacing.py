"""Per-host request pacing (DESIGN.md section 6, "Polite fetching").

The clock and the sleep are injected, so tests can check pacing without
waiting.
"""

from collections.abc import Callable


class Pacer:
    """Keep at least ``interval`` seconds between the starts of requests to one host.

    :param interval: The minimum gap, in seconds, between two requests to the
        same host. Zero turns pacing off.
    :param clock: A monotonic clock, in seconds.
    :param sleep: Sleeps for the given number of seconds.
    :raises ValueError: If ``interval`` is negative.
    """

    def __init__(
        self,
        interval: float,
        clock: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        if interval < 0:
            raise ValueError("Pacer: interval must not be negative")
        self._interval = interval
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}

    def wait(self, host: str) -> None:
        """Sleep until a request to ``host`` is allowed, then record it as started.

        :param host: The host the next request goes to, in lowercase.
        """
        last = self._last.get(host)
        if last is not None:
            delay = last + self._interval - self._clock()
            if delay > 0:
                self._sleep(delay)
        self._last[host] = self._clock()

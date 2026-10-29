import time

import pyotp


def current_code(secret):
    """The current TOTP code of *secret*, still valid for at least two seconds.

    Arches' sign-in and the project's enrolment verify with no tolerance
    window: a code read at the end of its 30 s step would fail one step later.
    """
    totp = pyotp.TOTP(secret)
    left = totp.interval - time.time() % totp.interval
    if left < 2:
        time.sleep(left)
    return totp.now()

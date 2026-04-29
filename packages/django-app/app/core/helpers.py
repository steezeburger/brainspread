import functools
import random
import secrets
import string
from datetime import date

import pytz
from django.utils import timezone


def today_for_user(user) -> date:
    """Return today's date in the given user's timezone.

    Falls back to UTC when the user has no timezone set or pytz can't
    resolve the value. Always use this instead of ``date.today()`` /
    ``datetime.now().date()`` when computing a "today" that the user
    will see in the UI - the server clock is UTC and would otherwise
    flip a day early for users west of UTC.
    """
    try:
        if user and user.timezone and user.timezone != "UTC":
            user_tz = pytz.timezone(user.timezone)
            return timezone.now().astimezone(user_tz).date()
    except Exception:
        pass
    return timezone.now().date()


def generate_membership_token():
    return secrets.token_urlsafe()


def generate_email_activation_code():
    """
    Generate Email Activation Token to be sent for mobile devices
    example: ZSDF123
    """
    token = "".join(random.choice(string.ascii_uppercase) for i in range(4))
    return token + str(random.randint(111, 999))


def get_random_password():
    letters = string.ascii_letters + string.punctuation
    result_str = "A1!" + "".join(random.choice(letters) for i in range(10))
    return result_str


def generate_signup_key():
    letters = string.ascii_uppercase + string.digits
    res = "".join(random.choice(letters) for i in range(10))
    return res


def rgetattr(obj, attr, *args):
    """
    Recursive get attribute.
    Get attr from obj. attr can be nested.
    Returns None if attribute does not exist.

    Ex: val = rgetattr(obj, 'some.nested.property')
    """

    def _getattr(obj, attr):
        if hasattr(obj, attr):
            return getattr(obj, attr, *args)
        return None

    return functools.reduce(_getattr, [obj] + attr.split("."))

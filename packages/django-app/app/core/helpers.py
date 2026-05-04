import functools
import os
import random
import secrets
import string
from datetime import date

import pytz
from django.utils import timezone

_PROD_ENVIRONMENTS = {"prod", "production"}


def is_production_env() -> bool:
    """Whether the running deploy is configured as production.

    Treats `ENVIRONMENT` env var values in {"prod", "production"} as
    production. Anything else (staging, local dev with the var unset)
    is considered non-prod. Mirrors the convention already used by
    send_due_reminders_command.
    """
    return os.environ.get("ENVIRONMENT", "").strip().lower() in _PROD_ENVIRONMENTS


def is_staging_theme_available() -> bool:
    """Single source of truth for gating the garish staging theme.

    The theme exists in the user model's choices on every env (so the
    DB schema and admin stay consistent), but the user-facing settings
    UI and the theme-update API gate it on this check so it can't be
    selected on production.
    """
    return not is_production_env()


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

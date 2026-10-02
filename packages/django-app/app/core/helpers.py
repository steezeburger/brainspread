import functools
import hashlib
import random
import secrets
import string


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


# Every MCP access key starts with this, so the authentication class
# can tell one apart from a legacy DRF token without a DB lookup.
MCP_ACCESS_KEY_PREFIX = "bsmcp_"
# How much of the key the settings UI shows to tell tokens apart.
MCP_ACCESS_KEY_DISPLAY_LENGTH = 12


def generate_mcp_access_key() -> str:
    return MCP_ACCESS_KEY_PREFIX + secrets.token_urlsafe(32)


def hash_mcp_access_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def is_mcp_access_key(key: str) -> bool:
    return key.startswith(MCP_ACCESS_KEY_PREFIX)

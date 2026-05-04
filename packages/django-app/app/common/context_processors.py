from django.conf import settings

from core.helpers import is_staging_theme_available


def static_version(request):
    return {"STATIC_VERSION": settings.STATIC_VERSION}


def staging_theme_flag(request):
    return {"IS_STAGING_THEME_AVAILABLE": is_staging_theme_available()}

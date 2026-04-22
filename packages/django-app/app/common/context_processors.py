from django.conf import settings


def static_version(request):
    return {"STATIC_VERSION": settings.STATIC_VERSION}

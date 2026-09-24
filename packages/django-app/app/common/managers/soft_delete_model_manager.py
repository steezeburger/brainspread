from django.db import models
from django.utils.timezone import now


class SoftDeleteQuerySet(models.query.QuerySet):
    def delete(self, *args, **kwargs):
        if kwargs.get("force_delete", None):
            return super().delete()

        return super().update(is_active=False, deleted_at=now())

    def undelete(self, *args, **kwargs):
        return super().update(is_active=True, deleted_at=None)

    def alive(self):
        return self.filter(is_active=True)

    def deleted(self):
        return self.filter(is_active=False)


class SoftDeleteModelManager(models.Manager):
    """
    Custom manager for models that use SoftDeleteTimestampMixin.
    """

    def get_queryset(self):
        return SoftDeleteQuerySet(self.model)

    def deleted(self):
        return self.get_queryset().deleted()

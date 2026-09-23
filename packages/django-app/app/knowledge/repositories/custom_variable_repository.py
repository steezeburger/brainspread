from typing import Dict, Optional

from django.db.models import QuerySet

from common.repositories.base_repository import BaseRepository

from ..models import CustomVariable


class CustomVariableRepository(BaseRepository):
    model = CustomVariable

    @classmethod
    def list_for_user(cls, user) -> QuerySet:
        return cls.get_queryset().filter(user=user).order_by("name")

    @classmethod
    def expansions_for_user(cls, user) -> Dict[str, str]:
        """name → raw expansion, the shape ``TokenContext.custom_tokens`` wants."""
        return dict(
            cls.get_queryset().filter(user=user).values_list("name", "expansion")
        )

    @classmethod
    def get_by_uuid(cls, uuid: str, user) -> Optional[CustomVariable]:
        try:
            return cls.get_queryset().get(uuid=uuid, user=user)
        except cls.model.DoesNotExist:
            return None

    @classmethod
    def name_taken(cls, user, name: str, exclude_uuid: Optional[str] = None) -> bool:
        qs = cls.get_queryset().filter(user=user, name=name)
        if exclude_uuid:
            qs = qs.exclude(uuid=exclude_uuid)
        return qs.exists()

    @classmethod
    def create(cls, *, user, name: str, expansion: str) -> CustomVariable:
        return cls.model.objects.create(user=user, name=name, expansion=expansion)

    @classmethod
    def update(cls, variable: CustomVariable, **fields) -> CustomVariable:
        for key, value in fields.items():
            setattr(variable, key, value)
        variable.save()
        return variable

    @classmethod
    def delete(cls, variable: CustomVariable) -> None:
        variable.delete()

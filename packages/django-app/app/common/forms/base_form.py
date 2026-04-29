from typing import Any, Dict, Mapping, Optional

from django import forms
from stringcase import snakecase


def snake_case_and_rename_id(key: str) -> str:
    """
    snake cases key and renames to 'pk' if 'id', because 'id' shadows built in
    """
    new_key = snakecase(key)
    if new_key == "id":
        new_key = "pk"
    return new_key


class BaseForm(forms.Form):
    def __init__(
        self,
        data: Mapping[str, Any],
        files: Optional[Mapping[str, Any]] = None,
    ):
        """
        Snake cases all form keys.
        Ex: `createdBy` -> `created_by`

        `files` is optional and only relevant for forms that accept
        multipart uploads; Django's FileField pulls from `self.files`,
        not `self.data`, so it must be passed through separately.
        """
        transformed_data = {
            snake_case_and_rename_id(key): val for key, val in data.items()
        }
        transformed_files = (
            {snake_case_and_rename_id(key): val for key, val in files.items()}
            if files
            else None
        )
        super().__init__(transformed_data, transformed_files)

    def clean(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        cleaned_data = super().clean()

        # NOTE - Django forms will set non required fields to None or to an empty string if
        #        the form field is not passed into the form.

        # Filter for fields that are passed through the form and remove fields that where
        # not passed into the form. File fields live on self.files (not
        # self.data) under multipart submissions, so include both sources.
        submitted_keys = set(self.data) | set(self.files or {})
        cleaned_data = {
            form_field: cleaned_data[form_field]
            for form_field in submitted_keys
            if form_field in cleaned_data
        }

        return cleaned_data

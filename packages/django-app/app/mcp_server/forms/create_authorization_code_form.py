from django import forms

from core.repositories.user_repository import UserRepository
from mcp_server.forms.authorization_request_form import AuthorizationRequestForm


class CreateAuthorizationCodeForm(AuthorizationRequestForm):
    """Approval submission: the validated authorization request plus
    the user who approved it."""

    user = forms.ModelChoiceField(queryset=UserRepository.get_queryset())

"""Keep password hashing and validation in Django rather than application code."""

from django.contrib.auth.forms import UserCreationForm

from accounts.models import User


class RegistrationForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        # Email is deliberately not collected until recovery/verification exists.
        fields = ("username",)

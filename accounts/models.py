"""Define the user model before other applications create user foreign keys."""

from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Use Django authentication now; extend profile fields only when needed."""

"""Tests that Django is configured with the project's custom user model."""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser

from accounts.models import User


def test_auth_user_model_setting_points_to_accounts_user():
    assert settings.AUTH_USER_MODEL == "accounts.User"


def test_get_user_model_returns_the_custom_user():
    user_model = get_user_model()

    assert user_model is User
    assert issubclass(user_model, AbstractUser)


def test_django_auth_uses_the_swapped_user_model():
    from django.contrib.auth.models import User as AuthUser

    assert AuthUser._meta.swapped == "accounts.User"


def test_custom_user_is_stored_by_the_migrated_schema(db):
    user = get_user_model().objects.create_user(
        username="phase0-user",
        password="phase0-password",
    )

    assert user.pk is not None
    assert get_user_model().objects.filter(username="phase0-user").exists()

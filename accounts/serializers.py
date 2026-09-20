"""API serializers for the accounts app."""

from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.tokens import RefreshToken

from academics.models import Department

User = get_user_model()


class DepartmentSummarySerializer(serializers.ModelSerializer):
    """Compact read-only department representation."""

    class Meta:
        model = Department
        fields = ("id", "name", "code")
        read_only_fields = fields


class CurrentUserSerializer(serializers.ModelSerializer):
    """Read-only representation of the authenticated user.

    Deliberately exposes nothing but identity, role and department: no password
    material, tokens or permission internals.
    """

    full_name = serializers.SerializerMethodField()
    department = DepartmentSummarySerializer(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "role",
            "department",
        )
        read_only_fields = fields

    def get_full_name(self, obj) -> str:
        """Return first/last name, falling back to the username when both are blank."""
        return obj.get_full_name() or obj.get_username()


class ActiveUserTokenRefreshSerializer(TokenRefreshSerializer):
    """Refresh serializer that re-validates the token's user on every call.

    ``TokenRefreshSerializer`` only verifies the token's signature and expiry, so
    a user deactivated after receiving a refresh token could otherwise keep
    minting access tokens. Here the user referenced by the token must still exist
    and be active, otherwise the refresh is rejected.
    """

    def validate(self, attrs):
        refresh = RefreshToken(attrs["refresh"])
        user = User.objects.filter(pk=refresh.get(api_settings.USER_ID_CLAIM)).first()
        if user is None or not user.is_active:
            raise AuthenticationFailed(
                "No active account found for this token.",
                code="user_inactive",
            )
        return super().validate(attrs)

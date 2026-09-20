"""Authentication and identity API views."""

from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.generics import RetrieveAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from accounts.serializers import ActiveUserTokenRefreshSerializer, CurrentUserSerializer


class LoginView(TokenObtainPairView):
    """Issue a JWT access/refresh pair for valid credentials. Public endpoint.

    Inactive accounts cannot log in: Django's authentication backend refuses to
    authenticate them and SimpleJWT's authentication rule rejects the resulting
    empty user. Only the tokens are returned, never user details.
    """

    authentication_classes: list = []
    permission_classes = [AllowAny]

    @extend_schema(
        tags=["auth"],
        summary="Obtain a JWT access/refresh token pair",
        description=(
            "Exchanges a username and password for a short-lived access token and a "
            "refresh token. Invalid credentials and inactive accounts are rejected "
            "with HTTP 401."
        ),
        request=inline_serializer(
            name="LoginRequest",
            fields={
                "username": serializers.CharField(),
                "password": serializers.CharField(style={"input_type": "password"}),
            },
        ),
        responses={
            200: inline_serializer(
                name="LoginResponse",
                fields={
                    "access": serializers.CharField(),
                    "refresh": serializers.CharField(),
                },
            )
        },
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class RefreshView(TokenRefreshView):
    """Exchange a refresh token for a new access token. Public endpoint."""

    authentication_classes: list = []
    permission_classes = [AllowAny]
    serializer_class = ActiveUserTokenRefreshSerializer

    @extend_schema(
        tags=["auth"],
        summary="Refresh an access token",
        description=(
            "Returns a new access token for a valid refresh token. The token's user is "
            "re-checked on every call, so deactivated users can no longer refresh."
        ),
        request=inline_serializer(
            name="TokenRefreshRequest",
            fields={"refresh": serializers.CharField()},
        ),
        responses={
            200: inline_serializer(
                name="TokenRefreshResponse",
                fields={"access": serializers.CharField()},
            )
        },
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class MeView(RetrieveAPIView):
    """Identity, role and department of the authenticated user. Read-only."""

    serializer_class = CurrentUserSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["accounts"],
        summary="Current user",
        description=(
            "Returns the authenticated user's identity, application role and department "
            "(null when none is assigned). Requires a valid access token."
        ),
        responses={200: CurrentUserSerializer},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_object(self):
        return self.request.user

from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from .models import User, Organization


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["id", "name", "slug"]


class UserSerializer(serializers.ModelSerializer):
    org = OrganizationSerializer(read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "email", "role", "org"]


class BreatheTokenSerializer(TokenObtainPairSerializer):
    """Embeds user info in the JWT response so the frontend doesn't need a second call."""
    def validate(self, attrs):
        data = super().validate(attrs)
        data["user"] = UserSerializer(self.user).data
        return data


class BreatheTokenView(TokenObtainPairView):
    serializer_class = BreatheTokenSerializer

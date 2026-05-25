from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .serializers import BreatheTokenView
from .views import MeView

urlpatterns = [
    path("token/", BreatheTokenView.as_view(), name="token_obtain"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("me/", MeView.as_view(), name="me"),
]

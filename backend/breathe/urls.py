from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import JsonResponse

urlpatterns = [
    path("health/", lambda request: JsonResponse({"status": "ok"})),
    path("admin/", admin.site.urls),
    path("api/auth/", include("apps.core.urls")),
    path("api/", include("apps.ingestion.urls")),
    path("api/", include("apps.emissions.urls")),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

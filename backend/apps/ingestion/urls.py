from django.urls import path
from .views import UploadView, JobListView, JobDetailView

urlpatterns = [
    path("jobs/", JobListView.as_view(), name="job_list"),
    path("jobs/upload/", UploadView.as_view(), name="upload"),
    path("jobs/<uuid:job_id>/", JobDetailView.as_view(), name="job_detail"),
]

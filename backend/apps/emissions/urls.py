from django.urls import path
from .views import (
    RecordListView, RecordDetailView, ReviewActionView,
    BulkReviewView, LockView, DashboardSummaryView,
)

urlpatterns = [
    path("records/", RecordListView.as_view(), name="record_list"),
    path("records/summary/", DashboardSummaryView.as_view(), name="summary"),
    path("records/bulk-review/", BulkReviewView.as_view(), name="bulk_review"),
    path("records/lock/", LockView.as_view(), name="lock"),
    path("records/<uuid:record_id>/", RecordDetailView.as_view(), name="record_detail"),
    path("records/<uuid:record_id>/review/", ReviewActionView.as_view(), name="review_action"),
]

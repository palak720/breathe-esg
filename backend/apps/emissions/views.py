from django.utils import timezone
from django.db.models import Q, Count, Sum
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import serializers, status

from .models import EmissionRecord


class EmissionRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmissionRecord
        fields = [
            "id", "scope", "category", "period_start", "period_end",
            "facility_code", "facility_name", "country_code", "department",
            "activity_quantity_source", "activity_unit_source",
            "activity_quantity", "activity_unit",
            "co2e_kg", "emission_factor", "emission_factor_source",
            "vendor", "description",
            "raw_data", "source_row_ref",
            "flag_reasons", "status", "review_note",
            "reviewed_by", "reviewed_at", "locked_at",
            "is_manually_edited", "edit_history",
            "created_at", "updated_at",
            "job",
        ]
        read_only_fields = [
            "id", "org", "job", "scope", "category", "raw_data",
            "source_row_ref", "created_at", "updated_at",
            "reviewed_by", "reviewed_at", "locked_at",
        ]


class RecordListView(APIView):
    def get(self, request):
        qs = EmissionRecord.objects.filter(org=request.user.org).select_related("job", "reviewed_by")

        # Filters
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status__in=status_filter.split(","))

        scope_filter = request.query_params.get("scope")
        if scope_filter:
            qs = qs.filter(scope__in=[int(s) for s in scope_filter.split(",")])

        category_filter = request.query_params.get("category")
        if category_filter:
            qs = qs.filter(category__in=category_filter.split(","))

        job_filter = request.query_params.get("job")
        if job_filter:
            qs = qs.filter(job_id=job_filter)

        flagged_only = request.query_params.get("flagged_only")
        if flagged_only == "true":
            qs = qs.exclude(flag_reasons=[])

        search = request.query_params.get("search")
        if search:
            qs = qs.filter(
                Q(vendor__icontains=search) |
                Q(description__icontains=search) |
                Q(facility_code__icontains=search) |
                Q(facility_name__icontains=search)
            )

        # Pagination
        page_size = int(request.query_params.get("page_size", 50))
        page = int(request.query_params.get("page", 1))
        start = (page - 1) * page_size
        total = qs.count()

        records = qs[start:start + page_size]
        return Response({
            "count": total,
            "page": page,
            "page_size": page_size,
            "results": EmissionRecordSerializer(records, many=True).data,
        })


class RecordDetailView(APIView):
    def get(self, request, record_id):
        try:
            record = EmissionRecord.objects.get(id=record_id, org=request.user.org)
        except EmissionRecord.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(EmissionRecordSerializer(record).data)

    def patch(self, request, record_id):
        try:
            record = EmissionRecord.objects.get(id=record_id, org=request.user.org)
        except EmissionRecord.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if record.status == "LOCKED":
            return Response({"error": "Record is locked for audit and cannot be modified."}, status=400)

        editable_fields = {"activity_quantity", "activity_unit", "co2e_kg", "review_note", "flag_reasons"}
        edit_entries = []
        now = timezone.now()

        for field in editable_fields:
            if field in request.data:
                old_val = getattr(record, field)
                new_val = request.data[field]
                if str(old_val) != str(new_val):
                    edit_entries.append({
                        "field": field,
                        "old_value": str(old_val),
                        "new_value": str(new_val),
                        "edited_by": request.user.username,
                        "edited_at": now.isoformat(),
                    })
                    setattr(record, field, new_val)

        if edit_entries:
            record.edit_history = record.edit_history + edit_entries
            record.is_manually_edited = True

        # Recompute co2e if quantity changed and no explicit co2e override
        if "activity_quantity" in request.data and "co2e_kg" not in request.data and record.emission_factor:
            from decimal import Decimal
            record.co2e_kg = (Decimal(str(record.activity_quantity)) * record.emission_factor).quantize(Decimal("0.000001"))

        record.save()
        return Response(EmissionRecordSerializer(record).data)


class ReviewActionView(APIView):
    """
    POST /api/records/<id>/review/
    body: { "action": "approve" | "flag" | "reject", "note": "..." }
    """
    VALID_ACTIONS = {"approve", "flag", "reject"}
    ACTION_TO_STATUS = {"approve": "APPROVED", "flag": "FLAGGED", "reject": "REJECTED"}

    def post(self, request, record_id):
        try:
            record = EmissionRecord.objects.get(id=record_id, org=request.user.org)
        except EmissionRecord.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if record.status == "LOCKED":
            return Response({"error": "Locked records cannot be reviewed."}, status=400)

        action = request.data.get("action", "").lower()
        if action not in self.VALID_ACTIONS:
            return Response({"error": f"action must be one of {self.VALID_ACTIONS}"}, status=400)

        note = request.data.get("note", "")
        record.status = self.ACTION_TO_STATUS[action]
        record.review_note = note
        record.reviewed_by = request.user
        record.reviewed_at = timezone.now()
        record.save()
        return Response(EmissionRecordSerializer(record).data)


class BulkReviewView(APIView):
    """
    POST /api/records/bulk-review/
    body: { "ids": [...], "action": "approve" | "reject", "note": "..." }
    Analysts need to be able to approve a whole job's clean rows at once.
    """
    def post(self, request):
        ids = request.data.get("ids", [])
        action = request.data.get("action", "").lower()
        note = request.data.get("note", "")

        if action not in {"approve", "reject"}:
            return Response({"error": "action must be approve or reject"}, status=400)

        new_status = "APPROVED" if action == "approve" else "REJECTED"
        now = timezone.now()

        updated = EmissionRecord.objects.filter(
            id__in=ids,
            org=request.user.org,
        ).exclude(status="LOCKED").update(
            status=new_status,
            review_note=note,
            reviewed_by=request.user,
            reviewed_at=now,
        )
        return Response({"updated": updated})


class LockView(APIView):
    """
    POST /api/records/lock/
    body: { "job_id": "..." }
    Locks all APPROVED records from a job for audit. ADMIN only.
    """
    def post(self, request):
        if request.user.role != "ADMIN":
            return Response({"error": "Only admins can lock records."}, status=403)

        job_id = request.data.get("job_id")
        if not job_id:
            return Response({"error": "job_id required"}, status=400)

        now = timezone.now()
        locked = EmissionRecord.objects.filter(
            job_id=job_id,
            org=request.user.org,
            status="APPROVED",
        ).update(status="LOCKED", locked_at=now)

        pending = EmissionRecord.objects.filter(job_id=job_id, org=request.user.org, status="PENDING").count()
        flagged = EmissionRecord.objects.filter(job_id=job_id, org=request.user.org, status="FLAGGED").count()

        return Response({
            "locked": locked,
            "still_pending": pending,
            "still_flagged": flagged,
        })


class DashboardSummaryView(APIView):
    """
    Aggregated stats for the review dashboard header.
    """
    def get(self, request):
        org = request.user.org
        qs = EmissionRecord.objects.filter(org=org)

        job_id = request.query_params.get("job")
        if job_id:
            qs = qs.filter(job_id=job_id)

        by_status = dict(qs.values_list("status").annotate(c=Count("id")).values_list("status", "c"))
        by_scope = dict(qs.values_list("scope").annotate(c=Count("id")).values_list("scope", "c"))
        co2e_by_scope = {
            row["scope"]: float(row["total"] or 0)
            for row in qs.values("scope").annotate(total=Sum("co2e_kg"))
        }

        flagged_count = qs.exclude(flag_reasons=[]).count()

        return Response({
            "by_status": by_status,
            "by_scope": by_scope,
            "co2e_by_scope_kg": co2e_by_scope,
            "flagged_rows": flagged_count,
            "total_records": qs.count(),
        })

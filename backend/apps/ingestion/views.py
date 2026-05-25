from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework import serializers

from .models import IngestionJob, ParseError
from apps.emissions.models import EmissionRecord
from . import parsers


class IngestionJobSerializer(serializers.ModelSerializer):
    parse_errors = serializers.SerializerMethodField()

    class Meta:
        model = IngestionJob
        fields = [
            "id", "source_type", "status", "original_filename",
            "uploaded_at", "processed_at",
            "row_count_total", "row_count_parsed", "row_count_failed",
            "metadata", "error_detail", "parse_errors",
        ]

    def get_parse_errors(self, obj):
        return list(obj.parse_errors.values("row_ref", "error_message", "raw_content")[:20])


class UploadView(APIView):
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        source_type = request.data.get("source_type")
        if source_type not in dict(IngestionJob.SOURCE_TYPES):
            return Response(
                {"error": f"source_type must be one of: {list(dict(IngestionJob.SOURCE_TYPES).keys())}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        file_obj = request.FILES.get("file")
        if not file_obj:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)

        org = request.user.org
        if not org:
            return Response({"error": "User has no organization"}, status=status.HTTP_403_FORBIDDEN)

        job = IngestionJob.objects.create(
            org=org,
            source_type=source_type,
            status="PROCESSING",
            uploaded_file=file_obj,
            original_filename=file_obj.name,
            uploaded_by=request.user,
        )

        try:
            parser_map = {
                "SAP_FLAT_FILE": parsers.sap,
                "UTILITY_CSV":   parsers.utility,
                "TRAVEL_CSV":    parsers.travel,
            }
            parser = parser_map[source_type]
            job.uploaded_file.seek(0)
            result = parser.parse(job.uploaded_file, job, org)

            records = result["records"]
            errors = result["errors"]

            # Bulk create records
            EmissionRecord.objects.bulk_create(records, batch_size=500)

            # Store parse errors
            ParseError.objects.bulk_create([
                ParseError(
                    job=job,
                    row_ref=e.get("row", "?"),
                    raw_content=str(e.get("raw", "")),
                    error_message=e.get("error", ""),
                )
                for e in errors
            ], batch_size=500)

            job.status = "COMPLETE"
            job.row_count_total = len(records) + len(errors)
            job.row_count_parsed = len(records)
            job.row_count_failed = len(errors)
            job.metadata = result.get("metadata", {})
            job.processed_at = timezone.now()
            job.save()

        except Exception as e:
            import traceback
            job.status = "FAILED"
            job.error_detail = traceback.format_exc()
            job.save()
            return Response(
                {"error": str(e), "job_id": str(job.id)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(IngestionJobSerializer(job).data, status=status.HTTP_201_CREATED)


class JobListView(APIView):
    def get(self, request):
        jobs = IngestionJob.objects.filter(org=request.user.org).order_by("-uploaded_at")[:50]
        return Response(IngestionJobSerializer(jobs, many=True).data)


class JobDetailView(APIView):
    def get(self, request, job_id):
        try:
            job = IngestionJob.objects.get(id=job_id, org=request.user.org)
        except IngestionJob.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        return Response(IngestionJobSerializer(job).data)

from rest_framework.views import APIView
from rest_framework.response import Response
from .serializers import UserSerializer


class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)

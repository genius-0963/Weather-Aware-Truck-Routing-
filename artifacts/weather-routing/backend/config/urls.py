import os
from django.conf import settings
from django.http import FileResponse, Http404
from django.urls import include, path, re_path

def serve_spa(request):
    index_file = os.path.join(settings.FRONTEND_DIST, "index.html")
    if os.path.exists(index_file):
        return FileResponse(open(index_file, "rb"), content_type="text/html")
    raise Http404("Frontend build not found. Run 'pnpm run build' first.")

urlpatterns = [
    path("api/v1/", include("routing.urls")),
    re_path(r"^.*$", serve_spa),
]

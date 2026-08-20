"""Root URL configuration for the Anga backend.

Every public route lives under /api/. There is no Django admin and no
session/auth surface: this service is a read-only JSON API in front of
Weather-AI, so anything else would be attack surface with no purpose.
"""

from django.urls import include, path

from weather.views import HealthView

urlpatterns = [
    path("api/", include("weather.urls")),
    path("api/", include("locations.urls")),
    path("healthz", HealthView.as_view(), name="health"),
]

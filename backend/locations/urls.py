from django.urls import path

from locations.views import LocationSearchView

urlpatterns = [
    path("locations/", LocationSearchView.as_view(), name="location-search"),
]

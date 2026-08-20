from django.urls import path

from weather.views import StatsView, WeatherView

urlpatterns = [
    path("weather/", WeatherView.as_view(), name="weather"),
    path("meta/stats/", StatsView.as_view(), name="meta-stats"),
]

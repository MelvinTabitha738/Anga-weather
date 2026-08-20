from rest_framework import serializers

from locations.models import Location


class LocationSerializer(serializers.ModelSerializer):
    """Public shape of a gazetteer entry.

    Coordinates are intentionally omitted: they are an implementation detail of
    how we talk to Weather-AI, and the frontend only ever needs the slug.
    """

    label = serializers.CharField(source="display_name", read_only=True)

    class Meta:
        model = Location
        fields = ["slug", "name", "county", "kind", "label"]

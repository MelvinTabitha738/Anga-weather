import logging

from rest_framework.response import Response
from rest_framework.views import APIView

from locations.selectors import DEFAULT_SEARCH_LIMIT, search_locations
from locations.serializers import LocationSerializer

logger = logging.getLogger(__name__)


class LocationSearchView(APIView):
    """GET /api/locations/?q=nai&limit=8

    Autocomplete for Kenyan counties and towns. Served entirely from
    PostgreSQL - this endpoint never touches Weather-AI, so typing in the
    search box costs no upstream quota.
    """

    throttle_scope = "locations"

    def get(self, request):
        query = request.query_params.get("q", "")
        limit = request.query_params.get("limit", DEFAULT_SEARCH_LIMIT)
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = DEFAULT_SEARCH_LIMIT

        results = search_locations(query, limit=limit)
        return Response(
            {
                "query": query,
                "count": len(results),
                "results": LocationSerializer(results, many=True).data,
            }
        )

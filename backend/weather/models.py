"""The weather app intentionally defines no models.

Weather responses are volatile, expire on a TTL and need atomic single-flight
coordination, so they belong in Redis - not PostgreSQL. Persisting every
upstream response to a relational table would add write load and a growth
problem while solving nothing the cache does not already solve.

PostgreSQL's role in this project is the Kenya gazetteer; see locations.models.
"""

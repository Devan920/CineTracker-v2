"""Compatibility re-export of TMDBClient and metadata models under utils.tmdb_client."""

from enrichment.tmdb_client import (
    TMDB_BACKDROP_BASE,
    TMDB_POSTER_BASE,
    WIKIPEDIA_API_URL,
    TMDBClient,
    TMDBMetadata,
    build_fuzzy_title_variants,
)

__all__ = [
    "TMDBClient",
    "TMDBMetadata",
    "TMDB_POSTER_BASE",
    "TMDB_BACKDROP_BASE",
    "WIKIPEDIA_API_URL",
    "build_fuzzy_title_variants",
]

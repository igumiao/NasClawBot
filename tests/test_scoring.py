from app.domain.models import ResourceCandidate, SearchConstraints
from app.domain.scoring import score_candidates


def test_speed_mode_prefers_more_seeders_when_relevance_is_similar():
    constraints = SearchConstraints(
        query_text="dune tonight",
        title="Dune Part Two",
        media_type="movie",
        optimization_goal="speed",
        urgency="high",
    )
    candidates = [
        ResourceCandidate(
            id="1",
            title="Dune Part Two 2024 1080p",
            media_type="movie",
            year=2024,
            resolution="1080p",
            seeders=20,
            size="10 GB",
            source="mteam",
        ),
        ResourceCandidate(
            id="2",
            title="Dune Part Two 2024 1080p",
            media_type="movie",
            year=2024,
            resolution="1080p",
            seeders=120,
            size="12 GB",
            source="mteam",
        ),
    ]

    scored = score_candidates(constraints, candidates)

    assert scored[0].candidate.id == "2"
    assert "seeder-boost-speed" in scored[0].reasons


def test_media_type_mismatch_is_penalized_even_with_more_seeders():
    constraints = SearchConstraints(
        query_text="dune movie",
        title="Dune Part Two",
        media_type="movie",
        optimization_goal="balanced",
    )
    candidates = [
        ResourceCandidate(
            id="movie-ok",
            title="Dune Part Two 2024 1080p",
            media_type="movie",
            year=2024,
            resolution="1080p",
            seeders=25,
            size="10 GB",
            source="mteam",
        ),
        ResourceCandidate(
            id="tv-wrong",
            title="Dune Part Two S01 1080p",
            media_type="tv",
            year=2024,
            resolution="1080p",
            seeders=260,
            size="20 GB",
            source="mteam",
        ),
    ]

    scored = score_candidates(constraints, candidates)

    assert scored[0].candidate.id == "movie-ok"


def test_quality_mode_prefers_higher_resolution_for_same_title():
    constraints = SearchConstraints(
        query_text="dune high quality",
        title="Dune Part Two",
        media_type="movie",
        preferred_resolution="2160p",
        optimization_goal="quality",
    )
    candidates = [
        ResourceCandidate(
            id="1080-many-seeders",
            title="Dune Part Two 2024 1080p",
            media_type="movie",
            year=2024,
            resolution="1080p",
            seeders=220,
            size="12 GB",
            source="mteam",
        ),
        ResourceCandidate(
            id="4k-fewer-seeders",
            title="Dune Part Two 2024 2160p",
            media_type="movie",
            year=2024,
            resolution="2160p",
            seeders=80,
            size="28 GB",
            source="mteam",
        ),
    ]

    scored = score_candidates(constraints, candidates)

    assert scored[0].candidate.id == "4k-fewer-seeders"
    assert "quality-resolution-boost" in scored[0].reasons


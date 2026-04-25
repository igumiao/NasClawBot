from app.domain.models import ResourceCandidate
from app.workflow.graph import build_workflow


class StubExtractor:
    def invoke(self, message: str):
        return {
            "query_text": message,
            "title": "Dune Part Two",
            "media_type": "movie",
            "optimization_goal": "speed",
            "urgency": "high",
        }


class StubSearchTool:
    def __call__(self, constraints):
        return [
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
        ]


def test_workflow_returns_confirmation_payload():
    graph = build_workflow(extractor=StubExtractor(), search_tool=StubSearchTool())
    result = graph.invoke({"session_id": "s1", "user_message": "I want to watch Dune tonight"})

    assert result["confirmation_payload"]["recommended_result_id"] == "2"
    assert result["status"] == "awaiting_confirmation"

from movierec.api.schemas import MovieRecommendation


def search_movies(query_text: str, top_k: int = 5) -> list[MovieRecommendation]:
    # TODO: Embed query_text using Hugging Face model
    # TODO: Query Qdrant vector database

    # mock return value so the GUI can test integration immediately
    return [
        MovieRecommendation(
            id=101,
            title="Stub Movie: The Lion King",
            score=0.95,
            overview="The circle of life...",
        )
    ]

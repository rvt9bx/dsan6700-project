from movierec.api.schemas import MovieRecommendation, ParticipantScore


def search_movies(query_text: str, top_k: int = 5) -> list[MovieRecommendation]:
    # TODO: Embed query_text using Hugging Face model
    # TODO: Query Qdrant vector database

    # Mock return value for GUI integration testing
    return [
        MovieRecommendation(
            id="101",
            title="Stub Movie: The Lion King",
            group_score=0.95,
            individual_scores=[
                ParticipantScore(participant_index=0, score=0.95),
            ],
            overview="The circle of life...",
        )
    ]

from pydantic import BaseModel, Field


class RecommendationRequest(BaseModel):
    query_texts: list[str] = Field(
        ...,
        min_length=1,
        description="Each participant's description of what they want to watch",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        description="Total number of movies to return, including the top pick",
    )


class ParticipantScore(BaseModel):
    participant_index: int = Field(
        ...,
        ge=0,
        description="Zero-based index of the participant's query",
    )
    score: float = Field(
        ...,
        description="Similarity score for this participant",
    )


class MovieRecommendation(BaseModel):
    id: str
    title: str
    overview: str | None = None
    year: int | None = None
    genres: list[str] = Field(default_factory=list)
    poster_path: str | None = Field(
        default=None,
        description="TMDB poster path, e.g. /abc.jpg; prefix with an image base URL",
    )
    group_score: float = Field(
        ...,
        description="Aggregated similarity score for the group",
    )
    individual_scores: list[ParticipantScore] = Field(default_factory=list)


class RecommendationResponse(BaseModel):
    top_pick: MovieRecommendation
    alternates: list[MovieRecommendation] = Field(default_factory=list)

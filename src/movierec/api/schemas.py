from pydantic import BaseModel, Field


class RecommendationRequest(BaseModel):
    query_texts: list[str] = Field(
        ...,
        min_length=1,
        description="Each participant's description of what they want to watch",
    )
    top_k: int = Field(default=5, ge=1)


class MovieRecommendation(BaseModel):
    id: int | str
    title: str
    score: float
    overview: str | None = None


class RecommendationResponse(BaseModel):
    results: list[MovieRecommendation]

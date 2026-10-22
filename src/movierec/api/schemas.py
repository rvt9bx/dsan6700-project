from pydantic import BaseModel, Field


class RecommendationRequest(BaseModel):
    query_text: str = Field(
        ...,
        description="User text input from the GUI describing what they want to watch",
    )
    top_k: int = Field(5, description="Number of movie recommendations to return")


class MovieRecommendation(BaseModel):
    id: int | str
    title: str
    score: float
    overview: str | None = None


class RecommendationResponse(BaseModel):
    results: list[MovieRecommendation]

from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints

MAX_PARTICIPANTS = 6  # the UI's largest group
MAX_TOP_K = 20
MAX_QUERY_CHARS = 1000

QueryText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUERY_CHARS),
]
JobState = Literal["pending", "running", "completed", "failed"]


class RecommendationRequest(BaseModel):
    query_texts: list[QueryText] = Field(
        ...,
        min_length=1,
        max_length=MAX_PARTICIPANTS,
        description=f"Each participant's description of what they want to watch: 1 to "
        f"{MAX_PARTICIPANTS} people, each 1 to {MAX_QUERY_CHARS} characters, not blank",
        examples=[["a cozy mystery with a twist", "something funny, nothing too long"]],
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=MAX_TOP_K,
        description="Total number of movies to return, including the top pick",
    )


class JobAccepted(BaseModel):
    job_id: str = Field(
        ..., description="Use this id to check the job's status and results"
    )
    status: JobState


class JobStatus(BaseModel):
    job_id: str
    status: JobState
    error: str | None = Field(
        default=None, description="Why the job failed; null unless status is failed"
    )


class HealthStatus(BaseModel):
    status: Literal["ok"]


class ReadyStatus(BaseModel):
    status: Literal["ready", "not ready"]
    detail: str | None = Field(
        default=None, description="What is not ready, and what to check"
    )


class ErrorMessage(BaseModel):
    detail: str = Field(..., description="What went wrong")


class WatchEvent(BaseModel):
    job_id: str = Field(
        ...,
        max_length=64,
        description="The recommendation job the results came from",
    )
    movie_id: str = Field(
        ...,
        max_length=32,
        description="TMDB id of the movie the group chose",
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

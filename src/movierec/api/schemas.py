from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

MAX_PARTICIPANTS = 6  # the UI's largest group
MAX_TOP_K = 20
MAX_QUERY_CHARS = 1000
MIN_YEAR, MAX_YEAR = 1930, 2026
ALLOWED_GENRES = frozenset(
    {
        "Action",
        "Adventure",
        "Animation",
        "Comedy",
        "Crime",
        "Documentary",
        "Drama",
        "Family",
        "Fantasy",
        "History",
        "Horror",
        "Music",
        "Mystery",
        "Romance",
        "Science Fiction",
        "TV Movie",
        "Thriller",
        "War",
        "Western",
    }
)

QueryText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUERY_CHARS),
]
JobState = Literal["pending", "running", "completed", "failed"]


class PickFilters(BaseModel):
    """One person's optional genre and release-year limits."""

    genres: list[str] = Field(
        default_factory=list,
        max_length=len(ALLOWED_GENRES),
        description="Match any of these genres; empty means any genre",
    )
    year_min: int | None = Field(
        default=None,
        ge=MIN_YEAR,
        le=MAX_YEAR,
        description="Earliest release year, inclusive",
    )
    year_max: int | None = Field(
        default=None,
        ge=MIN_YEAR,
        le=MAX_YEAR,
        description="Latest release year, inclusive",
    )

    @field_validator("genres")
    @classmethod
    def _known_genres(cls, genres: list[str]) -> list[str]:
        """Reject genres not in ALLOWED_GENRES; sort and drop duplicates."""
        unknown = sorted(set(genres) - ALLOWED_GENRES)
        if unknown:
            raise ValueError(f"unknown genres: {unknown}")
        return sorted(set(genres))

    @model_validator(mode="after")
    def _years_ordered(self):
        """Reject a year range whose start is after its end."""
        if (
            self.year_min is not None
            and self.year_max is not None
            and self.year_min > self.year_max
        ):
            raise ValueError("year_min must not be greater than year_max")
        return self


class RecommendationRequest(BaseModel):
    """Body of POST /recommend: what each person wants to watch."""

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
    filters: list[PickFilters] | None = Field(
        default=None,
        description="Optional genre/year filters, one per entry in query_texts, same order. "
        "Each applies only to the candidates retrieved for that person's query.",
        examples=[[{"genres": ["Mystery"], "year_min": 1990}, {}]],
    )

    @model_validator(mode="after")
    def _one_filter_per_query(self):
        """Require one filter entry per query, when filters are sent."""
        if self.filters is not None and len(self.filters) != len(self.query_texts):
            raise ValueError("filters needs exactly one entry per query_texts entry")
        return self


class JobAccepted(BaseModel):
    """Reply to POST /recommend: the new job's id and state."""

    job_id: str = Field(
        ..., description="Use this id to check the job's status and results"
    )
    status: JobState


class JobStatus(BaseModel):
    """A job's current state, and why it failed if it did."""

    job_id: str
    status: JobState
    error: str | None = Field(
        default=None, description="Why the job failed; null unless status is failed"
    )


class HealthStatus(BaseModel):
    """Reply from /health: the app is running."""

    status: Literal["ok"]


class ReadyStatus(BaseModel):
    """Reply from /ready: whether Qdrant is up and the movies are loaded."""

    status: Literal["ready", "not ready"]
    detail: str | None = Field(
        default=None, description="What is not ready, and what to check"
    )


class ErrorMessage(BaseModel):
    """The JSON body of every error response."""

    detail: str = Field(..., description="What went wrong")


class WatchEvent(BaseModel):
    """Body of POST /events/watch: the movie a group chose to watch."""

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
    """How well a movie matches one person's description."""

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
    """One recommended movie, with its group and per-person scores."""

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
    """A finished job's results: the top pick and the alternates."""

    top_pick: MovieRecommendation
    alternates: list[MovieRecommendation] = Field(default_factory=list)

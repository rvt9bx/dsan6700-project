from fastapi import FastAPI
from movierec.api.schemas import RecommendationRequest, RecommendationResponse
from movierec.retrieval.search import search_movies

app = FastAPI(title="Movie Semantic Recommendation API", version="0.1.0")


@app.post("/recommend", response_model=RecommendationResponse)
async def get_recommendations(payload: RecommendationRequest):
    results = search_movies(payload.query_text, payload.top_k)
    return RecommendationResponse(results=results)

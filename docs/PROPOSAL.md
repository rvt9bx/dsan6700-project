# movierec: proposal

*Final Project Deliverable 1.*

## The problem
People often recognize the mood or feeling they are looking for in a movie but struggle to pick a specific title.
Existing tools, like streaming platforms, rely on genre filters, keywords, or watch history rather than letting users
describe what they want in their own words. This can become particularly difficult in group settings, where everyone
has different preferences and there’s usually no “fair” way to choose.

**Problem statement.** Our goal is to build a product that can help a person or group of people pick a movie to watch
when they know the general topic or feeling, but can’t settle on one.

## Who the users are
This product will have 2 main targets:
- **Primary:** a group of people, whether that's friends, coworkers, family, acquaintances, or even strangers.
- **Secondary:** individual people who don't know exactly what they're in the mood for. They might know the general
  feeling they want but can't land on a specific film.

Our app will give each person an equal say in group settings and ease a lot of personal stress in individual ones.

## Stakeholders
<!-- TODO: the user, legal and compliance, product, leadership, the engineers (us): what each one cares about. -->

## Data
We will use movie data from IMDB and TMDB. IMDB has movie information available to download in multiple gzipped .tsv
files, which we will download, combine, and filter in order to get a baseline dataset of popular movies. Then, to
gather more information such as movie descriptions (“overview” field) for the semantic search or poster images to
display in the app, we will use the TMDB API. The main preprocessing work will be filtering to a smaller subset of
movies, selecting relevant data to include in the metadata, and general text cleaning of whitespace, html tags, or
other json characters as needed so that the data is able to be embedded. We will also use the MovieLens dataset for
evaluation.

## Core analytic
The core analytic will be a semantic group recommendation system for movies. Either a single user or group of users
would each be able to describe in plain language a movie they would like to see. Our analytic would embed that query,
retrieve movies that match or are similar, and return a ranked top-N list. If it is for a group, it would take the
top-N of each query’s results, pool them together, score them against each original query, and aggregate those scores
in order to create a final ranking of recommendations for the entire group.

We will use an open source vector database for storing and querying the embeddings, and an open source embedding model
from HuggingFace. We can also use open source TMDB API Python wrappers like themoviedb or tmdbv3api. There are open
source libraries for more traditional group recommender systems, but since we aren’t taking into account user-item
interactions and we are just basing our recommendation on group/query similarity, we will probably code the pooled
scoring and ranking ourselves.

## Techniques
The team is considering employing techniques from both DSAN5000: Data Science and Analytics and DSAN5400: Computational
Ling Adv Python. The data collection process will potentially involve web scraping through APIs, and other rudimentary
data science concepts will be employed throughout the project (e.g. data collection, cleaning, filtering,
pre-processing, modeling, knowledge extraction, actionable recommendations). An embedding model like BERT or Word2Vec
will be utilized to represent movie descriptions as vectors to capture meaning while preserving contextual information.

We will also be learning new topics from outside of class. We are implementing semantic search, which will require a
vector database, as well as group aggregation with social-choice aggregation functions to combine each member's
results into a single group ranking, compared against each other during evaluation.

## Tech stack and deployment
The application will be written in Python, with dependencies and environments managed through uv (pyproject.toml and
uv.lock). The backend will be a FastAPI service with Pydantic models validating incoming queries (e.g., number of group
members and each member's description) and outgoing ranked recommendations. Movie metadata (titles, genres, release
years, ratings, poster paths) and their embeddings will be stored together in Chroma, an open-source vector database,
persisted through a Docker volume so data survives container rebuilds. The frontend will be a simple web interface
that calls the FastAPI endpoints.

The app will be deployed on a Jetstream2 m3.small instance (2 CPU cores, 6 GB RAM, 20 GB root disk). Because the
semantic search relies on a small embedding model, no GPU is required. Movie embeddings will be generated once in
advance, so each user request only needs to process the new description and compare it against the saved movies.

## Evaluation
**Retrieval quality.** First, we want to evaluate the retrieval quality of our semantic search engine. This asks the
question: are the retrieved films for a single query relevant? To do this we will use the MovieLens dataset,
specifically the MovieLens tag genome dataset. This gives every movie a continuous relevant score across roughly 1100
descriptive tags (mood, style, subject matter, etc). We will use these tags to produce proxy ground-truth data for
evaluation. If we create a vector of tag weights, we can rank movies by their MovieLens tag genome scores against that
vector to get a top-N ground-truth pool. Then we can turn that tag vector into a natural language query and compare the
embedding model’s retrieval with the ground truth movies, using metrics like precision@K, recall@K, and Normalized
Discounted Cumulative Gain (nDCG) to evaluate. One limitation to this is that the MovieLens dataset is limited in
movies and tags that we can create ground truth for, so any niche semantic queries the actual application gets will
not be evaluated.

**Group recommendations.** We also want to evaluate the aggregated recommendations for groups: do the results produce
a good compromise between the users' tastes? It is difficult to evaluate the entire pipeline because we do not have
natural language queries connected to user reactions to recommended movies. Thus to do this, we would also use
MovieLens, but instead of the tag genome we would use the user movie ratings. From there we would use the grouprec
Python package to construct synthetic user groups, which can be similar, dissimilar, or random users. For each person
in the group, we can take some of their highly rated films as a ground truth preference group, and use a few highly
rated movies to create a proxy query. Then using each proxy query we can retrieve movies, perform the pooled group
ranking, and compare precision, recall, and nDCG against each individuals’ hold out group to get a per-member score.
Since we are using a few highly rated movies per person as input instead of a natural language query, we can either
average the scores per person so that a single movie isn’t an outlier, or use the genome tags / overview to create a
proxy natural language query from them to begin with. These per-person scores can be aggregated to mean precision,
minimum recall, etc to create group-level metrics. This can be run for each social-choice aggregation function to
evaluate and compare them.

**Configuration and operations.** Misconfigurations will be evaluated by tracking the frequency and impact of
configuration-related errors during deployment and testing. To reduce misconfigurations, the team will conduct regular
configuration audits, use `.env` files and appropriate secrets management, and automate environment checks through
CI/CD pipelines. The team will also standardize environment variables and clearly document expected values so that
configuration errors can be identified and resolved quickly. We also plan to evaluate latency and resource usage, i.e.
how quickly the app returns recommendations and how much of the instance's resources it uses.

## Risks and limitations
In regards to anticipated limitations or challenges, the JetStream2 Instance (m3.small) currently only has 2 CPU cores,
6 GB RAM, 20 GB root disk. The compute limitations could become a bottleneck as the project begins to involve large
datasets, memory-intensive processing, or computationally expensive models: “The single most important habit that will
protect [our] work this semester is shelving an instance the moment [we] stop using it.” Compute usage also has an
associated service unit cost (2.00 SUs/hr), so inefficient code or unnecessarily long-running instances could consume
the available allocation quickly. Moreover, a configuration that works on m3.small may not scale well as the dataset or
number of users grows. Although, these resources will improve as the course progresses. Deployment automation could
introduce dependency or configuration problems between development and production environments, making the application
more difficult to deploy reliably. There are also inherent security risks when deploying to a cloud environment:
unauthorized access, exposed secrets, insecure APIs, and improperly configured permissions. The team members will need
to adhere to proper remote tracking practices while collaborating on the project.

## Scope
Due to time constraints, we may not be able to explore more sophisticated aggregation methods, conduct a more extensive
evaluation of group satisfaction, or improve the application’s overall scalability. But we will divide the work across
major components, including data collection and preprocessing, semantic retrieval and recommendation logic, backend and
database development, frontend development, deployment, and evaluation to ensure we carry out and manage the project
effectively within our constraints.

## Goals
<!-- TODO: Certain / Likely / Stretch. -->

## Citations
- ACM Digital Library: A Survey on Group Recommender Systems: Evaluation Techniques and Metrics
- ACM Digital Library: The Tag Genome: Encoding Community Knowledge
- ACM Digital Library: Revisiting the Tag Relevance Prediction Problem
- arXiv: Recent Developments in Recommender Systems: A Survey
- GeeksforGeeks: Implementing Semantic Search with Vector Database
- GroupLens: MovieLens Datasets
- IMDb: Non-Commercial Datasets
- Jetstream2 Documentation: Main Overview
- Movie Disco: Movie Recommendation Tool
- TMDB: Developer API Documentation

# import packages
import pandas as pd


def clean_imdb_data() -> None:
    """Clean IMDB title and ratings data, output filtered movies CSV."""
    # import movie title dataset

    # loop through chunks
    all_data = []
    for chunk in pd.read_csv(
        "data/imdb/title.basics.tsv",
        sep="\t",
        usecols=["tconst", "titleType", "primaryTitle", "startYear", "isAdult"],
        dtype=object,
        chunksize=10000,
    ):
        # select movies released after 1925
        chunk = chunk[chunk["titleType"] == "movie"]
        chunk = chunk[chunk["isAdult"] == "0"]
        chunk = chunk[(chunk["startYear"] >= "1930") & (chunk["startYear"] != "\\N")]
        all_data.append(chunk)

    # concat dataframes together
    titles_df = pd.concat(all_data)

    # get all unique ids
    movie_ids = titles_df.tconst.unique()

    # import ratings dataset

    # loop through chunks
    all_data = []
    for chunk in pd.read_csv(
        "data/imdb/title.ratings.tsv", sep="\t", dtype=object, chunksize=10000
    ):
        # select ratings where the id is in the cleaned movie dataset
        chunk = chunk[chunk["tconst"].isin(movie_ids)]
        all_data.append(chunk)

    # concat dataframes together
    ratings_df = pd.concat(all_data)

    # display first few rows
    ratings_df.head()

    # join titles and ratings
    df = titles_df.merge(ratings_df, how="left", on="tconst")

    # drop where there are no ratings / votes
    df = df.dropna(axis=0)

    # get movies above 2000 votes
    df["numVotes"] = df["numVotes"].astype(int)
    threshold_df = df[df.numVotes >= 2000]

    # save to csv
    threshold_df.to_csv("data/clean/imdb_movies.csv", index=False)


if __name__ == "__main__":
    clean_imdb_data()

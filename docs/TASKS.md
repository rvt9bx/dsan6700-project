# From architecture to tasks

How the architecture became work. Each line is a GitHub issue; each issue gets a branch and a pull request that a
teammate reviews. The first milestone is a **walking skeleton**: the thinnest version that works end to end.

## Milestone 1: walking skeleton (everything connected, nothing good yet)
1. Project setup: `pyproject.toml`, uv, ruff, pytest, CI on pushes to `main` and on pull requests.
2. Settings: a `Settings` class read from the environment.
3. <!-- Data in: load and validate the input -->
4. <!-- A model interface and the simplest model that fits it -->
5. <!-- Core output step, with a test that proves it works -->
6. The API: <!-- endpoints -->, `/health`, `/ready`, with schemas.
7. <!-- The user-facing page or interface -->
8. Docker and Compose; deploy on Jetstream2; only the app's port open.

## Milestone 2: measure
9. <!-- Run the baseline on your evaluation data; record metrics -->
10. <!-- Error analysis: where does it fail? -->

## Milestone 3: first users (Homework 3)
11. Write the user brief; open the testing window; answer every issue.

## Milestone 4: iterate
12. <!-- Try better models behind the same interface; pick one by the numbers and by user feedback -->
13. <!-- Ship it by changing a setting, and measure again -->

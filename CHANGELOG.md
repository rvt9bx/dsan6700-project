# Changelog

<!--next-version-placeholder-->

## v0.2.0 (11/23/2026)

### Added

- Group recommendations: each person describes what they want, and the app picks one movie for the group, with alternates
- Choose how the group's picks are combined: Nash (default, favors movies everyone likes), average, geometric mean, or least misery
- Filter recommendations by genre and release year
- Real movie data: about 30,000 movies from IMDb and TMDB, searched by meaning in a vector database
- Posters, release years, and genres on every recommendation
- Share or copy tonight's pick, reuse your last group, and change your pick before the search
- A busy message with a countdown that retries when the service is overloaded or starting up
- Click logging for the "We're watching…" button, plus /metrics with Prometheus and Grafana dashboards for operators
- Every merge to main publishes a tested Docker image to the GitHub Container Registry

### Changed

- New home page and UI fixes from user testing, including a "No preference" option
- Served over HTTPS through Caddy

### Security

- Only ports 80 and 443 are reachable; the database and dashboards are private
- Rate limits on recommendations (429 with Retry-After) and limits on request size
- Secrets are scanned in CI, and every GitHub Action is pinned to a commit

## v0.1.0 (10/15/2026)

- First release of `movierec`!

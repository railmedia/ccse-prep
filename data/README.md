# data/

Committed here:

- `questions.sample.json` — 10 questions, for development and tests (Sprint 1).

**Never committed:**

- `manual/` — the official Instituto Cervantes PDF. Download it and ingest locally:

  ```bash
  mkdir -p data/manual
  curl -sSL -o data/manual/manual-ccse-2026.pdf \
    "https://cervantes.org/sites/public/produccion/files/2026-10/manual-preparacion-prueba-ccse-2026.pdf"
  make ingest PDF=data/manual/manual-ccse-2026.pdf
  ```

- The full parsed bank. It lives in Postgres, not in git, and is never baked into an image.

The manual and question bank are © Instituto Cervantes. They are downloaded by the person
running the app and are not redistributed by this project.

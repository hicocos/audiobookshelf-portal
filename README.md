# Audiobookshelf Portal

Twilight-inspired self-service account portal for Audiobookshelf.

## Safety

The first implementation phase is read-only against Audiobookshelf. User creation, deletion, disabling, and password changes must be explicitly enabled and tested with a disposable user first.

## Backend dev

```bash
cd backend
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]' respx
pytest -q
```

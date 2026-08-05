"""Allow ``python -m evals.meta_legal`` as an alias for score_recall."""

from evals.meta_legal.score_recall import main

if __name__ == "__main__":
    raise SystemExit(main())

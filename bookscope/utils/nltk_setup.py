"""One-call NLTK corpus bootstrap for nrclex / textblob.

Call ensure_nltk_data() once at app startup. Downloads are skipped if the
corpora are already present (no network call needed on subsequent runs).
"""

import nltk


def ensure_nltk_data() -> None:
    """Download NLTK corpora required by nrclex/textblob if not already present.

    Safe to call multiple times — each download is a no-op when the corpus
    already exists on disk.
    """
    _corpora = [
        ("tokenizers", "punkt_tab"),
        ("taggers", "averaged_perceptron_tagger_eng"),
        ("corpora", "wordnet"),
        ("corpora", "brown"),
        ("corpora", "conll2000"),
        ("corpora", "movie_reviews"),
    ]
    for category, name in _corpora:
        try:
            nltk.data.find(f"{category}/{name}")
        except LookupError:
            nltk.download(name, quiet=True)

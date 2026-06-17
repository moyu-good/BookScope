"""Download public-domain demo books from Project Gutenberg.

Usage:
    python scripts/download_demo.py

Books downloaded to data/demo/:
    - pride_and_prejudice.txt    (Austen, 1813)
    - sherlock_holmes.txt        (Doyle, 1892)
    - alice_in_wonderland.txt    (Carroll, 1865)
"""

import sys
import urllib.request
from pathlib import Path

DEMO_DIR = Path(__file__).parent.parent / "data" / "demo"

BOOKS = [
    (
        "pride_and_prejudice.txt",
        "https://www.gutenberg.org/files/1342/1342-0.txt",
        "Pride and Prejudice — Jane Austen",
    ),
    (
        "sherlock_holmes.txt",
        "https://www.gutenberg.org/files/1661/1661-0.txt",
        "The Adventures of Sherlock Holmes — Arthur Conan Doyle",
    ),
    (
        "alice_in_wonderland.txt",
        "https://www.gutenberg.org/files/11/11-0.txt",
        "Alice's Adventures in Wonderland — Lewis Carroll",
    ),
]


def download_book(filename: str, url: str, title: str) -> None:
    dest = DEMO_DIR / filename
    if dest.exists():
        print(f"  ✓ {title} (already downloaded)")
        return
    print(f"  ↓ {title} …", end=" ", flush=True)
    try:
        urllib.request.urlretrieve(url, dest)  # noqa: S310
        print(f"saved to {dest.relative_to(Path.cwd())}")
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)


def main() -> None:
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    print("Downloading BookScope demo books from Project Gutenberg…\n")
    for filename, url, title in BOOKS:
        download_book(filename, url, title)
    print("\nDone. Upload any file to BookScope via the sidebar.")


if __name__ == "__main__":
    main()

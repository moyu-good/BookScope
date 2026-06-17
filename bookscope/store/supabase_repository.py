"""SupabaseRepository — cloud-backed storage for shareable BookScope analyses.

Only used for the share/publish flow.  LocalRepository remains the default
for all library and save/load operations.

Prerequisites
-------------
1. Install the optional dependency::

       pip install "bookscope[share]"

2. Create the ``analyses`` table in your Supabase project::

       CREATE TABLE analyses (
           id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
           slug       text UNIQUE NOT NULL,
           title      text NOT NULL,
           book_type  text NOT NULL DEFAULT 'fiction',
           created_at timestamptz DEFAULT now(),
           data       jsonb NOT NULL,
           notes      jsonb,
           is_public  boolean DEFAULT false
       );

3. Set environment variables (or Streamlit secrets)::

       SUPABASE_URL = "https://<project>.supabase.co"
       SUPABASE_KEY = "<anon-public-key>"

Usage
-----
::

    from bookscope.store.supabase_repository import SupabaseRepository

    repo = SupabaseRepository()
    if repo.available:
        slug = repo.publish(result, book_type="fiction")   # → "a3f2c8b1"
        # share URL: <app-url>?share=a3f2c8b1

    # On the share view side:
    result = repo.load_by_slug(slug)  # None if not found or not public
"""

from __future__ import annotations

import os
import uuid as _uuid

from bookscope.store.repository import AnalysisResult


class SupabaseRepository:
    """Supabase-backed publish/share repository.

    This class is intentionally narrow: it only handles publish (save + mark
    public) and load-by-slug.  Full library management (list, delete, notes)
    uses :class:`LocalRepository` and is unaffected.

    Instantiation always succeeds.  Use :attr:`available` to check whether
    Supabase is configured and the ``supabase`` package is installed before
    calling any methods.
    """

    def __init__(self) -> None:
        self._url: str | None = (
            os.environ.get("SUPABASE_URL") or self._from_secrets("SUPABASE_URL")
        )
        self._key: str | None = (
            os.environ.get("SUPABASE_KEY") or self._from_secrets("SUPABASE_KEY")
        )
        self._client = None
        if self._url and self._key:
            try:
                from supabase import create_client  # optional dep

                self._client = create_client(self._url, self._key)
            except ImportError:
                pass  # supabase package not installed → available = False

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """``True`` when Supabase is configured and the client is ready."""
        return self._client is not None

    def publish(
        self,
        result: AnalysisResult,
        book_type: str = "fiction",
    ) -> str | None:
        """Save an analysis to Supabase and mark it as publicly shareable.

        Generates an 8-character slug from a UUID (collision probability
        negligible for typical usage volumes).

        Args:
            result:    The analysis to publish.
            book_type: Book type label ("fiction" / "academic" / "essay").

        Returns:
            8-character slug string on success, or ``None`` on any error.
            Callers should treat ``None`` as "share unavailable" and surface
            a generic error message — avoid leaking Supabase details to the UI.
        """
        if not self._client:
            return None

        slug = _uuid.uuid4().hex[:8]
        try:
            self._client.table("analyses").insert(
                {
                    "slug": slug,
                    "title": result.book_title,
                    "book_type": book_type,
                    "data": result.model_dump(),
                    "is_public": True,
                }
            ).execute()
            return slug
        except Exception:
            return None

    def load_by_slug(self, slug: str) -> AnalysisResult | None:
        """Load a publicly shared analysis by its 8-character slug.

        Security: the filter ``is_public = true`` is applied at the database
        query level — private analyses are never fetched, not filtered in Python.

        Args:
            slug: 8-character share slug from the URL query param.

        Returns:
            :class:`AnalysisResult` if found and public, else ``None``.
        """
        if not self._client:
            return None
        try:
            response = (
                self._client.table("analyses")
                .select("data")
                .eq("slug", slug)
                .eq("is_public", True)
                .single()
                .execute()
            )
            if response.data:
                return AnalysisResult.model_validate(response.data["data"])
        except Exception:
            pass
        return None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _from_secrets(key: str) -> str | None:
        """Read a value from Streamlit secrets (no-op outside Streamlit)."""
        try:
            import streamlit as st  # noqa: PLC0415

            return st.secrets.get(key)
        except Exception:
            return None

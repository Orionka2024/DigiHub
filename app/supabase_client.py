"""Supabase client singleton for DigiHub.

Initialised once per process. Uses the service-role key so that
server-side operations bypass Row Level Security.
"""
import os
import logging

_client = None


def get_supabase():
    """Return the shared Supabase client, creating it on first call."""
    global _client
    if _client is not None:
        return _client

    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()

    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY environment variables are required. "
            "Add them in Vercel → Project Settings → Environment Variables."
        )

    try:
        from supabase import create_client
        _client = create_client(url, key)
        logging.info("[Supabase] Client initialised for %s", url)
    except ImportError:
        raise RuntimeError(
            "supabase package is not installed. Add 'supabase' to requirements.txt."
        )

    return _client

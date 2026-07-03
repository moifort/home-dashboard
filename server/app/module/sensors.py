"""Shared multi-device sensor declaration parsing (transverse infrastructure).

The power sensors (POWER_SENSORS) and the plants (PLANTS_SENSORS) both declare
their devices in one env var of `;`-separated `topic:Name…` entries. This module
owns the common part — entry splitting, the first-`:` topic/rest split, the
empty/duplicate-topic policing and the storage slugs — while each domain keeps
its own slug policy (power groups same-name topics; plants split a trailing
numeric threshold).
"""
import logging
import unicodedata

logger = logging.getLogger(__name__)


def slugify(name: str) -> str:
    """Lowercase, accent-stripped, space-collapsed slug for storage keys."""
    ascii_name = (
        unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    )
    return "-".join(ascii_name.lower().split())


def topic_suffixed_slug(name: str, topic: str) -> str:
    """A per-topic storage slug for entries whose name slug would collide."""
    return f"{slugify(name)}-{slugify(topic.replace('/', ' '))}"


def parse_entries(raw: str, var_name: str) -> list[tuple[str, str]]:
    """Parse a `topic:rest;topic2:rest2` declaration into (topic, rest) pairs.

    Malformed entries (no `:`, empty topic or rest) and duplicate topics are
    skipped with a warning naming `var_name`. The rest keeps everything after
    the first `:` (labels may contain colons), stripped.
    """
    entries = []
    seen_topics = set()
    for entry in raw.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        if ":" not in entry:
            logger.warning("%s entry ignored (no ':' topic/name): %r", var_name, entry)
            continue
        topic, rest = entry.split(":", 1)
        topic, rest = topic.strip(), rest.strip()
        if not topic or not rest:
            logger.warning("%s entry ignored (empty topic or name): %r", var_name, entry)
            continue
        if topic in seen_topics:
            logger.warning("%s duplicate topic %r ignored: %r", var_name, topic, entry)
            continue
        seen_topics.add(topic)
        entries.append((topic, rest))
    return entries

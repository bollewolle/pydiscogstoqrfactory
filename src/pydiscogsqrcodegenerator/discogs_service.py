import re
import time
from datetime import date

import discogs_client

# Module-level cache for collection data, keyed by (username, folder_id).
# Each entry: {"timestamp": float, "items": list[dict]}
# Items contain: {"release": normalized dict, "formats": list[dict]}
_collection_cache: dict[tuple[str, int], dict] = {}
_CACHE_TTL = 300  # 5 minutes


class DiscogsService:
    """Wrapper around the python3-discogs-client library."""

    def __init__(self, consumer_key: str, consumer_secret: str, user_agent: str):
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.user_agent = user_agent
        self.client = discogs_client.Client(user_agent)
        self._identity = None

    def get_authorize_url(self, callback_url: str) -> tuple[str, str, str]:
        """Start OAuth flow. Returns (request_token, request_secret, authorize_url)."""
        self.client.set_consumer_key(self.consumer_key, self.consumer_secret)
        request_token, request_secret, authorize_url = (
            self.client.get_authorize_url(callback_url=callback_url)
        )
        return request_token, request_secret, authorize_url

    def get_access_token(
        self, request_token: str, request_secret: str, verifier: str
    ) -> tuple[str, str]:
        """Exchange verifier for access tokens. Returns (access_token, access_secret)."""
        self.client.set_consumer_key(self.consumer_key, self.consumer_secret)
        self.client.set_token(request_token, request_secret)
        access_token, access_secret = self.client.get_access_token(verifier)
        return access_token, access_secret

    def authenticate(self, access_token: str, access_secret: str) -> None:
        """Authenticate with existing tokens."""
        self.client.set_consumer_key(self.consumer_key, self.consumer_secret)
        self.client.set_token(access_token, access_secret)

    def get_identity(self) -> dict:
        """Get the authenticated user's identity."""
        if self._identity is None:
            identity = self.client.identity()
            self._identity = {
                "username": identity.username,
                "id": identity.id,
            }
        return self._identity

    def get_folders(self, username: str) -> list[dict]:
        """Get all collection folders for a user."""
        user = self.client.user(username)
        folders = []
        for folder in user.collection_folders:
            folders.append(
                {
                    "id": folder.id,
                    "name": folder.name,
                    "count": folder.count,
                }
            )
        return folders

    @staticmethod
    def _cache_is_fresh(entry: dict, now: float) -> bool:
        """A cache entry is fresh if it is marked persistent or within TTL."""
        if not entry:
            return False
        if entry.get("persistent"):
            return True
        return (now - entry["timestamp"]) < _CACHE_TTL

    def get_cached_folder_release_ids(self, username: str, folder_id: int) -> set[int] | None:
        """Get release IDs for a folder from cache, without triggering an API call.

        Returns None if the folder data is not cached.
        """
        now = time.time()
        key = (username, folder_id)
        cached = _collection_cache.get(key)
        if not self._cache_is_fresh(cached, now):
            return None
        return {item["release"]["id"] for item in cached["items"]}

    def _get_cached_items(self, username: str, folder_id: int) -> list[dict]:
        """Get or build cached collection data for a folder.

        Each item is a dict with:
            "release": normalized release dict,
            "formats": list of format dicts from the API
        """
        now = time.time()
        key = (username, folder_id)
        cached = _collection_cache.get(key)
        if self._cache_is_fresh(cached, now):
            return cached["items"]

        user = self.client.user(username)
        folder = self._find_folder(user, folder_id)
        folder_name = folder.name

        # Build folder_id -> name map for resolving items in the "All" folder
        if folder_id == 0:
            folder_names = {f.id: f.name for f in user.collection_folders}

        items = []
        for item in folder.releases:
            formats = getattr(item.release, "formats", None) or []
            if folder_id == 0:
                item_folder = self._get_item_folder_name(item, folder_names)
            else:
                item_folder = folder_name
            release_data = self._normalize_release(item, item_folder)
            items.append({"release": release_data, "formats": formats})

        existing = _collection_cache.get(key) or {}
        _collection_cache[key] = {
            "timestamp": now,
            "items": items,
            "persistent": existing.get("persistent", False),
        }
        return items

    def warm_cache(self, username: str, folder_id: int = 0) -> int:
        """Force a fresh fetch and mark the cache entry persistent.

        Persistent entries skip the TTL check so the landing page can report
        change counts between scheduled scans without triggering API calls.
        Returns the number of items cached.
        """
        key = (username, folder_id)
        # Drop any existing entry so _get_cached_items re-fetches.
        _collection_cache.pop(key, None)
        items = self._get_cached_items(username, folder_id)
        _collection_cache[key]["persistent"] = True
        return len(items)

    def get_cache_timestamp(self, username: str, folder_id: int) -> float | None:
        """Get the cache timestamp for a folder, or None if not cached."""
        cached = _collection_cache.get((username, folder_id))
        if cached:
            return cached["timestamp"]
        return None

    def invalidate_cache(self, username: str) -> None:
        """Remove all cached data for a user."""
        keys_to_remove = [k for k in _collection_cache if k[0] == username]
        for k in keys_to_remove:
            del _collection_cache[k]

    def invalidate_folder_cache(self, username: str, folder_id: int) -> None:
        """Remove cached data for a specific folder (and the All folder)."""
        for key in [(username, folder_id), (username, 0)]:
            _collection_cache.pop(key, None)

    def get_folder_releases(
        self,
        username: str,
        folder_id: int,
        sort: str = "artist",
        order: str = "asc",
    ) -> list[dict]:
        """Get all releases in a folder, sorted."""
        items = self._get_cached_items(username, folder_id)
        releases = [item["release"] for item in items]
        return self._sort_releases(releases, sort, order)

    def get_releases_since(
        self, username: str, since_date: date
    ) -> list[dict]:
        """Get releases added to collection since a given date (across all folders)."""
        items = self._get_cached_items(username, 0)
        releases = []
        for item in items:
            date_str = item["release"].get("date_added", "")
            if not date_str:
                continue
            try:
                added = date.fromisoformat(date_str[:10])
            except (ValueError, TypeError):
                continue
            if added >= since_date:
                releases.append(item["release"])
        return releases

    @staticmethod
    def _sort_releases(releases: list[dict], sort: str, order: str) -> list[dict]:
        """Sort releases by the given criteria."""
        reverse = order == "desc"
        key_map = {
            "artist": lambda r: r.get("artist", "").lower(),
            "year": lambda r: r.get("year", 0),
            "date_added": lambda r: r.get("date_added", ""),
        }
        key_func = key_map.get(sort, key_map["artist"])
        return sorted(releases, key=key_func, reverse=reverse)

    def get_collection_formats(self, username: str) -> list[dict]:
        """Get unique format names in the user's collection with counts."""
        items = self._get_cached_items(username, 0)

        format_counts: dict[str, dict] = {}
        for item in items:
            for fmt in item["formats"]:
                name = fmt.get("name", "Unknown")
                if name not in format_counts:
                    format_counts[name] = {"name": name, "count": 0, "has_sizes": False}
                format_counts[name]["count"] += 1
                descriptions = fmt.get("descriptions", [])
                if self._infer_size(descriptions):
                    format_counts[name]["has_sizes"] = True

        return sorted(format_counts.values(), key=lambda f: f["count"], reverse=True)

    def get_format_sizes(self, username: str, format_name: str) -> list[dict]:
        """Get unique sizes for a format name in the user's collection."""
        items = self._get_cached_items(username, 0)

        size_counts: dict[str, int] = {}
        unknown_count = 0
        for item in items:
            for fmt in item["formats"]:
                if fmt.get("name") != format_name:
                    continue
                descriptions = fmt.get("descriptions", [])
                inferred = self._infer_size(descriptions)
                if inferred:
                    size_counts[inferred] = size_counts.get(inferred, 0) + 1
                else:
                    unknown_count += 1

        result = sorted(
            [{"size": s, "count": c} for s, c in size_counts.items()],
            key=lambda x: x["count"],
            reverse=True,
        )
        if unknown_count and result:
            result.append({"size": "Unknown", "count": unknown_count})
        return result

    def get_releases_by_format(
        self,
        username: str,
        format_name: str,
        size: str = "",
        description_filter: list[str] | None = None,
    ) -> tuple[list[dict], list[str]]:
        """Get releases matching a format name and optional size.

        Returns (releases, available_descriptions) where available_descriptions
        are the non-size description values that can be used for filtering.
        """
        items = self._get_cached_items(username, 0)

        filter_set = set(description_filter) if description_filter else set()
        releases = []
        all_descriptions: set[str] = set()

        for item in items:
            for fmt in item["formats"]:
                if fmt.get("name") != format_name:
                    continue
                descriptions = fmt.get("descriptions", [])
                inferred = self._infer_size(descriptions)
                if size == "Unknown" and inferred:
                    continue
                if size and size != "Unknown" and inferred != size:
                    continue
                non_size = [d for d in descriptions if not self._is_size(d)]
                all_descriptions.update(non_size)
                if filter_set and not filter_set.issubset(set(non_size)):
                    continue
                releases.append(item["release"])
                break

        return releases, sorted(all_descriptions)

    # Descriptions that imply a 12" size when no explicit size is present
    _SIZE_INFERENCES: dict[str, str] = {
        "LP": '12"',
    }

    @staticmethod
    def _is_size(description: str) -> bool:
        """Check if a description is a physical size (e.g. '12\"', '7\"')."""
        return bool(re.match(r'^\d+"$', description))

    @classmethod
    def _infer_size(cls, descriptions: list[str]) -> str:
        """Determine the size from descriptions, inferring from known types if needed."""
        explicit = [d for d in descriptions if cls._is_size(d)]
        if explicit:
            return explicit[0]
        non_size = [d for d in descriptions if not cls._is_size(d)]
        for desc in non_size:
            if desc in cls._SIZE_INFERENCES:
                return cls._SIZE_INFERENCES[desc]
        return ""

    def _normalize_release(self, item, folder_name: str) -> dict:
        """Normalize a collection item into a flat dict."""
        release = item.release
        artist = self._format_artists(release.artists)
        date_added = getattr(item, "date_added", "")
        if hasattr(date_added, "isoformat"):
            date_added = date_added.isoformat()

        # Extract format info from the first format entry
        formats = getattr(release, "formats", None) or []
        format_name = ""
        format_size = ""
        format_descriptions = ""
        if formats:
            fmt = formats[0]
            format_name = fmt.get("name", "")
            descs = fmt.get("descriptions", [])
            non_sizes = [d for d in descs if not self._is_size(d)]
            format_size = self._infer_size(descs)
            format_descriptions = ", ".join(non_sizes)

        return {
            "id": release.id,
            "artist": artist,
            "title": release.title,
            "year": release.year or 0,
            "discogs_folder": folder_name,
            "url": f"https://www.discogs.com/release/{release.id}",
            "date_added": str(date_added) if date_added else "",
            "format_name": format_name,
            "format_size": format_size,
            "format_descriptions": format_descriptions,
        }

    @staticmethod
    def _find_folder(user, folder_id: int):
        """Find a collection folder by its ID (not list index)."""
        for folder in user.collection_folders:
            if folder.id == folder_id:
                return folder
        raise ValueError(f"Folder with ID {folder_id} not found")

    @staticmethod
    def _format_artists(artists) -> str:
        """Join multiple artists into a single string."""
        if not artists:
            return "Unknown Artist"
        return ", ".join(
            DiscogsService._strip_disambiguation(a.name) for a in artists
        )

    @staticmethod
    def _strip_disambiguation(name: str) -> str:
        """Remove Discogs disambiguation suffix like ' (2)' or ' (13)' from artist names."""
        return re.sub(r"\s+\(\d+\)$", "", name)

    @staticmethod
    def _map_sort_key(sort: str) -> str:
        """Map our sort names to Discogs API sort keys."""
        mapping = {
            "artist": "artist",
            "year": "year",
            "date_added": "added",
        }
        return mapping.get(sort, "artist")

    @staticmethod
    def _parse_date_added(item) -> date | None:
        """Parse the date_added field from a collection item."""
        from datetime import datetime

        date_val = getattr(item, "date_added", None)
        if not date_val:
            return None
        # Handle datetime objects directly
        if isinstance(date_val, datetime):
            return date_val.date()
        if isinstance(date_val, date):
            return date_val
        # Handle string format
        try:
            return date.fromisoformat(str(date_val)[:10])
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _get_item_folder_name(item, folder_names: dict[int, str] | None = None) -> str:
        """Get folder name from a collection item, with fallback."""
        folder_id = getattr(item, "folder_id", None)
        if folder_id is not None and folder_names:
            return folder_names.get(folder_id, "All")
        return "All"

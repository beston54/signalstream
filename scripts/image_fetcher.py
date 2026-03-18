"""
Image Fetcher Module

Fetches contextually relevant photos from Unsplash (primary) and
Pexels (backup) for report illustration. Implements local caching
and attribution tracking.
"""

import base64
import hashlib
import io
import json
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

import requests

logger = logging.getLogger(__name__)

# Try to import Pillow for image resizing
try:
    from PIL import Image
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False
    logger.warning("Pillow not installed; images will not be resized")

# Topic concept -> effective photo search terms
KEYWORD_MAP = {
    "climate": ["climate nature landscape", "sustainable environment"],
    "renewable energy": ["solar panels field", "wind turbines landscape"],
    "energy transition": ["power grid modern", "clean energy technology"],
    "environment": ["nature landscape pristine", "forest canopy aerial"],
    "sustainability": ["sustainable living green", "eco friendly technology"],
    "policy": ["government building modern", "civic engagement meeting"],
    "governance": ["international cooperation", "global unity"],
    "federalism": ["global connections network", "international collaboration"],
    "world federalism": ["global unity earth", "international cooperation"],
    "politics": ["civic engagement community", "democracy participation"],
    "technology": ["modern technology innovation", "digital transformation"],
    "data": ["data visualization screen", "analytics technology"],
    "community": ["diverse community gathering", "people collaboration"],
    "activism": ["peaceful civic engagement", "community organizing"],
}

# Section -> search intent template
SECTION_SEARCH_INTENTS = {
    "cover": "inspiring {topic} portrait",
    "methodology": "data analysis research technology",
    "engagement": "online community discussion collaboration",
    "sentiment": "emotions people diverse",
    "themes": "{topic} conceptual abstract",
    "recommendations": "strategic planning business meeting",
    "progress": "growth progress upward chart",
    "transparency": "honesty transparency open communication",
    "next_steps": "path forward direction future road",
}


class ImageFetcher:
    """Fetches and caches photos from Unsplash and Pexels APIs."""

    def __init__(self, config: dict, base_dir: str = "."):
        """
        Initialize with config containing API keys and cache settings.

        Args:
            config: Full config dict with image_apis section
            base_dir: Project root directory for resolving relative paths
        """
        self.config = config
        self.base_dir = Path(base_dir)
        image_config = config.get("image_apis", {})

        # Unsplash setup — env vars only, no config file fallback
        self.unsplash_key = (
            os.getenv("UNSPLASH_ACCESS_KEY")
            or os.getenv("UNSPLASH_API_KEY")
            or ""
        )
        self.unsplash_url = image_config.get("unsplash", {}).get(
            "base_url", "https://api.unsplash.com")
        self.unsplash_enabled = (
            image_config.get("unsplash", {}).get("enabled", True)
            and self.unsplash_key
            and not self.unsplash_key.startswith("YOUR_")
        )

        # Pexels setup — env vars only, no config file fallback
        self.pexels_key = (
            os.getenv("PEXELS_API_KEY")
            or ""
        )
        self.pexels_url = image_config.get("pexels", {}).get(
            "base_url", "https://api.pexels.com/v1")
        self.pexels_enabled = (
            image_config.get("pexels", {}).get("enabled", True)
            and self.pexels_key
            and not self.pexels_key.startswith("YOUR_")
        )

        # Cache setup
        cache_config = image_config.get("cache", {})
        self.cache_dir = self.base_dir / cache_config.get(
            "directory", "assets/images/cache")
        self.manifest_path = self.base_dir / cache_config.get(
            "manifest_file", "assets/images/cache_manifest.json")
        self.max_cache_age = cache_config.get("max_cache_age_days", 30)

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.manifest = self._load_manifest()

    def _load_manifest(self) -> dict:
        """Load cache manifest from JSON file."""
        if self.manifest_path.exists():
            try:
                with open(self.manifest_path, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {"images": {}}
        return {"images": {}}

    def _save_manifest(self) -> None:
        """Save cache manifest to JSON file."""
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.manifest_path, 'w') as f:
            json.dump(self.manifest, f, indent=2)

    def _get_cache_key(self, query: str) -> str:
        """Generate MD5-based cache key from search query."""
        return hashlib.md5(query.lower().strip().encode()).hexdigest()

    def _resize_image(self, image_bytes: bytes, max_width: int = 1200) -> bytes:
        """
        Resize image to max_width while maintaining aspect ratio.
        Falls back to original bytes if Pillow is unavailable.
        """
        if not HAS_PILLOW:
            return image_bytes

        try:
            img = Image.open(io.BytesIO(image_bytes))
            if img.width > max_width:
                ratio = max_width / img.width
                new_size = (max_width, int(img.height * ratio))
                img = img.resize(new_size, Image.LANCZOS)

            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=80, optimize=True)
            return buf.getvalue()
        except Exception as e:
            logger.warning(f"Image resize failed: {e}")
            return image_bytes

    def _get_cached_image(self, query: str) -> Optional[Dict[str, Any]]:
        """Check cache for existing image matching query."""
        cache_key = self._get_cache_key(query)
        cached = self.manifest.get("images", {}).get(cache_key)

        if cached:
            cache_path = self.cache_dir / cached["filename"]
            if cache_path.exists():
                cached_date = datetime.fromisoformat(cached["cached_at"])
                if datetime.now() - cached_date < timedelta(days=self.max_cache_age):
                    with open(cache_path, 'rb') as f:
                        img_data = base64.b64encode(f.read()).decode('utf-8')
                    return {
                        "data_uri": f"data:image/jpeg;base64,{img_data}",
                        "photographer": cached["photographer"],
                        "source": cached["source"],
                        "source_url": cached["source_url"],
                        "alt": cached.get("alt", query),
                        "from_cache": True,
                    }
        return None

    def _get_any_cached_image(self, exclude_queries: Optional[set] = None) -> Optional[Dict[str, Any]]:
        """
        Return any cached image from the manifest as a fallback.

        Useful when API keys are unavailable but previously cached photos exist.
        """
        exclude_queries = exclude_queries or set()
        images = self.manifest.get("images", {})
        for meta in images.values():
            query = meta.get("query", "")
            if query in exclude_queries:
                continue
            cache_path = self.cache_dir / meta.get("filename", "")
            if not cache_path.exists():
                continue
            try:
                with open(cache_path, 'rb') as f:
                    img_data = base64.b64encode(f.read()).decode('utf-8')
            except OSError:
                continue
            return {
                "data_uri": f"data:image/jpeg;base64,{img_data}",
                "photographer": meta.get("photographer", "Unknown"),
                "source": meta.get("source", "Cache"),
                "source_url": meta.get("source_url", ""),
                "alt": meta.get("alt", query or "Report photo"),
                "from_cache": True,
            }
        return None

    def _cache_image(
        self, query: str, image_bytes: bytes,
        photographer: str, source: str, source_url: str, alt: str
    ) -> Dict[str, Any]:
        """Save image to cache, resize it, and return data URI dict."""
        # Resize before caching
        image_bytes = self._resize_image(image_bytes)

        cache_key = self._get_cache_key(query)
        filename = f"{cache_key}.jpg"
        cache_path = self.cache_dir / filename

        with open(cache_path, 'wb') as f:
            f.write(image_bytes)

        self.manifest.setdefault("images", {})[cache_key] = {
            "filename": filename,
            "query": query,
            "photographer": photographer,
            "source": source,
            "source_url": source_url,
            "alt": alt,
            "cached_at": datetime.now().isoformat(),
        }
        self._save_manifest()

        img_b64 = base64.b64encode(image_bytes).decode('utf-8')
        return {
            "data_uri": f"data:image/jpeg;base64,{img_b64}",
            "photographer": photographer,
            "source": source,
            "source_url": source_url,
            "alt": alt,
            "from_cache": False,
        }

    def _search_unsplash(self, query: str, orientation: str = "landscape") -> Optional[Dict[str, Any]]:
        """Search Unsplash for a photo with the given orientation."""
        if not self.unsplash_enabled:
            return None

        try:
            resp = requests.get(
                f"{self.unsplash_url}/search/photos",
                params={
                    "query": query,
                    "per_page": 1,
                    "orientation": orientation,
                    "content_filter": "high",
                },
                headers={"Authorization": f"Client-ID {self.unsplash_key}"},
                timeout=15,
            )
            resp.raise_for_status()
            results = resp.json().get("results", [])

            if results:
                photo = results[0]
                img_url = photo["urls"]["regular"]
                img_resp = requests.get(img_url, timeout=30)
                img_resp.raise_for_status()

                return self._cache_image(
                    query=query,
                    image_bytes=img_resp.content,
                    photographer=photo["user"]["name"],
                    source="Unsplash",
                    source_url=photo["links"]["html"],
                    alt=photo.get("alt_description", query),
                )
        except Exception as e:
            logger.warning(f"Unsplash search failed for '{query}': {e}")

        return None

    def _search_pexels(self, query: str, orientation: str = "landscape") -> Optional[Dict[str, Any]]:
        """Search Pexels as fallback."""
        if not self.pexels_enabled:
            return None

        try:
            resp = requests.get(
                f"{self.pexels_url}/search",
                params={
                    "query": query,
                    "per_page": 1,
                    "orientation": orientation,
                },
                headers={"Authorization": self.pexels_key},
                timeout=15,
            )
            resp.raise_for_status()
            photos = resp.json().get("photos", [])

            if photos:
                photo = photos[0]
                img_url = photo["src"]["large"]
                img_resp = requests.get(img_url, timeout=30)
                img_resp.raise_for_status()

                return self._cache_image(
                    query=query,
                    image_bytes=img_resp.content,
                    photographer=photo["photographer"],
                    source="Pexels",
                    source_url=photo["url"],
                    alt=photo.get("alt", query),
                )
        except Exception as e:
            logger.warning(f"Pexels search failed for '{query}': {e}")

        return None

    def fetch_image(self, query: str, orientation: str = "landscape") -> Optional[Dict[str, Any]]:
        """
        Fetch a single image: check cache, then Unsplash, then Pexels.

        Args:
            query: Search query string
            orientation: Photo orientation (landscape, portrait, squarish)

        Returns:
            Dict with data_uri, photographer, source, source_url, alt
            or None if no image found
        """
        cached = self._get_cached_image(query)
        if cached:
            logger.debug(f"Cache hit for query: {query}")
            return cached

        result = self._search_unsplash(query, orientation)
        if result:
            return result

        result = self._search_pexels(query, orientation)
        if result:
            return result

        logger.info(f"No image found for query: {query}")
        return None

    def _derive_search_query(self, section: str, topics: List[str]) -> str:
        """
        Derive an effective photo search query from section name and topics.

        Each section gets a unique query by combining the section's visual
        intent with the report's subject matter, ensuring variety across
        the report.

        Args:
            section: Report section name (cover, methodology, etc.)
            topics: List of topic phrases from the report

        Returns:
            Search query string
        """
        primary_topic = topics[0] if topics else "sustainability"

        # Use section-specific intent templates to ensure unique queries
        # per section. The {topic} placeholder gets the primary topic.
        intent = SECTION_SEARCH_INTENTS.get(section, "{topic} professional")
        section_query = intent.format(topic=primary_topic)

        # For the cover page only, try the keyword map for a more
        # visually striking hero image
        if section == "cover":
            for keyword, search_terms in KEYWORD_MAP.items():
                if keyword in primary_topic.lower():
                    return search_terms[0]
            # For topics without a keyword match, use abstract/conceptual search
            # to avoid overly literal or potentially insensitive photo matches
            return f"{primary_topic} abstract conceptual"

        return section_query

    def fetch_report_images(
        self, topics: List[str], max_photos: int = 5
    ) -> Dict[str, Optional[Dict[str, Any]]]:
        """
        Fetch all images needed for a report.

        Args:
            topics: List of search phrases from the report
            max_photos: Maximum total photos to fetch

        Returns:
            Dict mapping section name to image data dict or None:
            {"cover": {...}, "themes": {...}, ...}
        """
        # Check cover_photo config
        report_config = self.config.get('design_system', {}).get('report', {})
        cover_photo_setting = report_config.get('cover_photo', 'auto')

        cache_only = not self.unsplash_enabled and not self.pexels_enabled
        if cache_only:
            logger.info("No image APIs configured; attempting cache-only photo fetch")

        photos = {}
        used_queries = set()
        section_priority = [
            "cover", "themes", "transparency", "methodology", "next_steps"
        ]

        for section in section_priority[:max_photos]:
            # Skip cover photo if disabled
            if section == "cover" and cover_photo_setting == "disabled":
                continue

            # Use custom image path for cover if specified
            if section == "cover" and cover_photo_setting not in ("auto", "disabled"):
                custom_path = Path(cover_photo_setting)
                if not custom_path.is_absolute():
                    custom_path = self.base_dir / custom_path
                if custom_path.exists():
                    try:
                        with open(custom_path, 'rb') as f:
                            img_data = base64.b64encode(f.read()).decode('utf-8')
                        mime = "image/jpeg" if str(custom_path).lower().endswith(('.jpg', '.jpeg')) else "image/png"
                        photos["cover"] = {
                            "data_uri": f"data:{mime};base64,{img_data}",
                            "photographer": "Custom",
                            "source": "Local",
                            "source_url": "",
                            "alt": "Cover image",
                            "from_cache": False,
                        }
                    except Exception as e:
                        logger.warning(f"Failed to load custom cover photo: {e}")
                else:
                    logger.warning(f"Custom cover photo not found: {custom_path}")
                continue

            query = self._derive_search_query(section, topics)
            used_queries.add(query)
            # Use portrait orientation for cover card (4:5 ratio)
            orientation = "portrait" if section == "cover" else "landscape"
            photo = self.fetch_image(query, orientation=orientation)
            if not photo and cache_only:
                photo = self._get_any_cached_image(exclude_queries=used_queries)
            if photo:
                photos[section] = photo
            time.sleep(0.5)

        logger.info(f"Fetched {len(photos)} report images")
        return photos

    def cleanup_cache(self, max_age_days: Optional[int] = None) -> int:
        """
        Remove cached images older than max_age_days.

        Args:
            max_age_days: Override for cache age limit

        Returns:
            Number of images removed
        """
        age_limit = max_age_days or self.max_cache_age
        cutoff = datetime.now() - timedelta(days=age_limit)
        removed = 0

        images = self.manifest.get("images", {})
        keys_to_remove = []

        for key, meta in images.items():
            try:
                cached_date = datetime.fromisoformat(meta["cached_at"])
                if cached_date < cutoff:
                    cache_path = self.cache_dir / meta["filename"]
                    if cache_path.exists():
                        cache_path.unlink()
                    keys_to_remove.append(key)
                    removed += 1
            except (KeyError, ValueError):
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del images[key]

        if removed > 0:
            self._save_manifest()
            logger.info(f"Cleaned up {removed} cached images")

        return removed

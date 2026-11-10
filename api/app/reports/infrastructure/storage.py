"""Supabase Storage adapter for report photos."""

from __future__ import annotations

import logging
from typing import Mapping

import httpx

from app.core.errors import PersistenceError
from app.reports.domain.ports import PhotoStorage

logger = logging.getLogger(__name__)

_EXTENSION_MAP: Mapping[str, str] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


class SupabasePhotoStorage(PhotoStorage):
    """Stores report photos in Supabase Storage and serves public CDN URLs."""

    def __init__(
        self,
        *,
        supabase_url: str,
        supabase_key: str,
        bucket: str = "Imagenes",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._supabase_url = supabase_url.rstrip("/")
        self._supabase_key = supabase_key
        self._bucket = bucket
        self._client = client
        self._owns_client = client is None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
            self._owns_client = True
        return self._client

    async def upload_photo(
        self,
        *,
        report_id: str,
        data: bytes,
        content_type: str,
    ) -> str:
        client = await self._get_client()
        ext = _EXTENSION_MAP.get(content_type, ".jpg")
        object_path = f"reports/{report_id}{ext}"
        upload_url = f"{self._supabase_url}/storage/v1/object/{self._bucket}/{object_path}"

        headers = {
            "apikey": self._supabase_key,
            "Authorization": f"Bearer {self._supabase_key}",
            "Content-Type": content_type,
            "x-upsert": "true",
        }

        try:
            response = await client.post(upload_url, headers=headers, content=data)
            if response.status_code not in (200, 201):
                logger.error(
                    "supabase storage upload failed",
                    extra={
                        "status_code": response.status_code,
                        "response_text": response.text,
                        "report_id": report_id,
                    },
                )
                raise PersistenceError(
                    "Failed to upload photo to Supabase storage."
                )
        except httpx.HTTPError as exc:
            logger.exception(
                "network error during supabase storage upload",
                extra={"report_id": report_id},
            )
            raise PersistenceError(
                "Network error connecting to storage service."
            ) from exc

        public_url = (
            f"{self._supabase_url}/storage/v1/object/public/"
            f"{self._bucket}/{object_path}"
        )
        logger.info(
            "report photo uploaded to supabase storage",
            extra={"report_id": report_id, "public_url": public_url},
        )
        return public_url

    async def get_photo(self, report_id: str) -> tuple[bytes, str] | None:
        return None

    async def delete_photo(self, photo_url: str) -> None:
        if not photo_url:
            return
        prefix = f"{self._supabase_url}/storage/v1/object/public/{self._bucket}/"
        if not photo_url.startswith(prefix):
            return
        object_path = photo_url[len(prefix) :]
        delete_url = f"{self._supabase_url}/storage/v1/object/{self._bucket}/{object_path}"
        headers = {
            "apikey": self._supabase_key,
            "Authorization": f"Bearer {self._supabase_key}",
        }
        client = await self._get_client()
        try:
            await client.delete(delete_url, headers=headers)
        except Exception:
            logger.warning(
                "failed to delete photo from supabase storage",
                extra={"photo_url": photo_url},
            )

    async def aclose(self) -> None:
        if self._owns_client and self._client and not self._client.is_closed:
            await self._client.aclose()


class InMemoryPhotoStorage(PhotoStorage):
    """In-memory photo store for testing."""

    def __init__(self, public_api_base_url: str | None = None) -> None:
        self.public_api_base_url = public_api_base_url
        self.photos: dict[str, tuple[bytes, str]] = {}

    async def upload_photo(
        self,
        *,
        report_id: str,
        data: bytes,
        content_type: str,
    ) -> str:
        self.photos[report_id] = (data, content_type)
        if self.public_api_base_url:
            return f"{self.public_api_base_url.rstrip('/')}/reports/photos/{report_id}"
        return f"/api/v1/reports/photos/{report_id}"

    async def get_photo(self, report_id: str) -> tuple[bytes, str] | None:
        return self.photos.get(report_id)

    async def delete_photo(self, photo_url: str) -> None:
        pass

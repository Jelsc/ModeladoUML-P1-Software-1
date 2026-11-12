"""Object storage (MinIO, S3 compatible) for the photos shared in the team chats.

Optional: without MINIO_ENDPOINT `get_storage()` returns None and the app keeps working, only without keeping the images.
"""
import io
import logging

from .config import settings

logger = logging.getLogger(__name__)
_storage = None


class PhotoStorage:
    def __init__(self, client, bucket):
        self.client, self.bucket, self._ready = client, bucket, False

    def _ensure_bucket(self):
        if not self._ready:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
            self._ready = True

    def put(self, key: str, data: bytes, mime: str) -> None:
        self._ensure_bucket()
        self.client.put_object(self.bucket, key, io.BytesIO(data), len(data), content_type=mime)

    def get(self, key: str) -> bytes:
        response = self.client.get_object(self.bucket, key)
        try:
            return response.read()
        finally:
            response.close(); response.release_conn()

    def delete_prefix(self, prefix: str) -> None:
        for item in list(self.client.list_objects(self.bucket, prefix=prefix, recursive=True)):
            self.client.remove_object(self.bucket, item.object_name)


def get_storage():
    global _storage
    if _storage is None and settings.MINIO_ENDPOINT:
        try:
            from minio import Minio
            _storage = PhotoStorage(Minio(settings.MINIO_ENDPOINT, access_key=settings.MINIO_ACCESS_KEY, secret_key=settings.MINIO_SECRET_KEY, secure=settings.MINIO_SECURE), settings.MINIO_BUCKET)
        except Exception as error:  # a missing package or bad settings must never break the chat
            logger.warning("photo_storage_unavailable exception_class=%s", type(error).__name__)
    return _storage

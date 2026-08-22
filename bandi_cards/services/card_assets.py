from __future__ import annotations

import io
import uuid
from pathlib import Path

import boto3
from fastapi import HTTPException, UploadFile, status
from PIL import Image, ImageOps, UnidentifiedImageError

from ..config import settings


MAX_IMAGE_BYTES = 10 * 1024 * 1024
ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp"}


class CardAssetStore:
    def __init__(self):
        self._s3 = None
        if settings.s3_endpoint_url and settings.s3_bucket_name:
            self._s3 = boto3.client(
                "s3",
                endpoint_url=settings.s3_endpoint_url,
                aws_access_key_id=settings.s3_access_key_id,
                aws_secret_access_key=settings.s3_secret_access_key,
                region_name=settings.s3_region,
            )

    async def save(
        self,
        upload: UploadFile,
        crop_x: float | None = None,
        crop_y: float | None = None,
        crop_width: float | None = None,
        crop_height: float | None = None,
    ) -> str:
        if upload.content_type not in ALLOWED_TYPES:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "PNG, JPEG, WebP만 업로드할 수 있습니다.")
        data = await upload.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "이미지는 최대 10MB입니다.")
        try:
            with Image.open(io.BytesIO(data)) as source:
                source.verify()
            with Image.open(io.BytesIO(data)) as source:
                image = ImageOps.exif_transpose(source).convert("RGB")
                if all(value is not None for value in (crop_x, crop_y, crop_width, crop_height)):
                    left = max(0, int(crop_x or 0))
                    top = max(0, int(crop_y or 0))
                    right = min(image.width, left + int(crop_width or 0))
                    bottom = min(image.height, top + int(crop_height or 0))
                    if right <= left or bottom <= top:
                        raise ValueError("invalid crop")
                    image = image.crop((left, top, right, bottom))
                image = ImageOps.fit(image, (900, 1200), method=Image.Resampling.LANCZOS)
                output = io.BytesIO()
                image.save(output, format="WEBP", quality=88, method=6)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "손상되었거나 자르기 영역이 잘못된 이미지입니다.") from exc

        key = f"cards/{uuid.uuid4()}.webp"
        body = output.getvalue()
        if self._s3:
            self._s3.put_object(Bucket=settings.s3_bucket_name, Key=key, Body=body, ContentType="image/webp")
        else:
            path = settings.upload_dir / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        return key

    def url(self, key: str) -> str:
        if self._s3:
            return self._s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.s3_bucket_name, "Key": key},
                ExpiresIn=900,
            )
        return f"/api/assets/{key}"

    def local_path(self, key: str) -> Path | None:
        if self._s3 or not key.startswith("cards/"):
            return None
        path = (settings.upload_dir / key).resolve()
        root = settings.upload_dir.resolve()
        if root not in path.parents:
            return None
        return path

    def delete(self, key: str) -> None:
        if self._s3:
            self._s3.delete_object(Bucket=settings.s3_bucket_name, Key=key)
            return
        path = self.local_path(key)
        if path and path.exists():
            path.unlink()


asset_store = CardAssetStore()

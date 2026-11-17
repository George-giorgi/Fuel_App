import os
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError

from backend.app.services import photo_storage
from backend.app.services.photo_storage import PhotoStorageError


class PhotoStorageTests(unittest.TestCase):
    def test_local_photos_use_private_files_and_remain_readable(self) -> None:
        with TemporaryDirectory() as upload_directory, patch.dict(
            os.environ, {"FUEL_PHOTO_STORAGE": "local"}
        ), patch.object(
            photo_storage, "METER_PHOTO_DIRECTORY", Path(upload_directory)
        ):
            storage_key, stored_path = photo_storage.store_photo(
                b"private photo",
                ".jpg",
                "image/jpeg",
            )

            self.assertIsNotNone(stored_path)
            self.assertEqual(stored_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(photo_storage.read_photo(storage_key), b"private photo")
            self.assertIsNone(photo_storage.read_photo("missing-photo.jpg"))

    def test_r2_upload_and_retrieval_use_a_private_unique_object(self) -> None:
        class FakeR2Client:
            def __init__(self) -> None:
                self.uploads: list[dict[str, object]] = []

            def put_object(self, **kwargs: object) -> dict[str, object]:
                self.uploads.append(kwargs)
                return {"ResponseMetadata": {"HTTPStatusCode": 200}}

            def get_object(self, **_: object) -> dict[str, object]:
                return {"Body": BytesIO(b"private R2 photo")}

        fake_client = FakeR2Client()
        with patch.dict(
            os.environ,
            {
                "FUEL_PHOTO_STORAGE": "r2",
                "R2_BUCKET_NAME": "private-meter-photos",
            },
        ), patch.object(
            photo_storage, "_r2_client", return_value=fake_client
        ):
            first_key, first_path = photo_storage.store_photo(
                b"private R2 photo", ".png", "image/png"
            )
            second_key, _ = photo_storage.store_photo(
                b"another photo", ".png", "image/png"
            )

            self.assertIsNone(first_path)
            self.assertNotEqual(first_key, second_key)
            self.assertEqual(photo_storage.read_photo(first_key), b"private R2 photo")
            self.assertNotIn("ACL", fake_client.uploads[0])

    def test_r2_storage_failure_does_not_return_an_uploaded_key(self) -> None:
        fake_client = Mock()
        fake_client.put_object.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied"}}, "PutObject"
        )
        with patch.dict(
            os.environ,
            {
                "FUEL_PHOTO_STORAGE": "r2",
                "R2_BUCKET_NAME": "private-meter-photos",
            },
        ), patch.object(photo_storage, "_r2_client", return_value=fake_client):
            with self.assertRaises(PhotoStorageError):
                photo_storage.store_photo(b"photo", ".jpg", "image/jpeg")

    def test_r2_photo_deletion_uses_the_configured_private_bucket(self) -> None:
        fake_client = Mock()
        fake_client.delete_object.return_value = {
            "ResponseMetadata": {"HTTPStatusCode": 204}
        }
        with patch.dict(
            os.environ,
            {
                "FUEL_PHOTO_STORAGE": "r2",
                "R2_BUCKET_NAME": "private-meter-photos",
            },
        ), patch.object(photo_storage, "_r2_client", return_value=fake_client):
            photo_storage.delete_photo("meter-photo.jpg")

        fake_client.delete_object.assert_called_once_with(
            Bucket="private-meter-photos",
            Key="meter-photo.jpg",
        )

    def test_r2_photo_cleanup_deletes_in_batches_of_one_thousand(self) -> None:
        fake_client = Mock()
        fake_client.delete_objects.return_value = {
            "ResponseMetadata": {"HTTPStatusCode": 200}
        }
        keys = [f"meter-photo-{index}.jpg" for index in range(1001)]
        with patch.dict(
            os.environ,
            {
                "FUEL_PHOTO_STORAGE": "r2",
                "R2_BUCKET_NAME": "private-meter-photos",
            },
        ), patch.object(
            photo_storage, "_r2_client", return_value=fake_client
        ):
            photo_storage.delete_photos(keys)

        self.assertEqual(fake_client.delete_objects.call_count, 2)
        first_batch = fake_client.delete_objects.call_args_list[0].kwargs
        second_batch = fake_client.delete_objects.call_args_list[1].kwargs
        self.assertEqual(len(first_batch["Delete"]["Objects"]), 1000)
        self.assertEqual(len(second_batch["Delete"]["Objects"]), 1)

    def test_r2_photo_cleanup_fails_when_a_batch_contains_errors(self) -> None:
        fake_client = Mock()
        fake_client.delete_objects.return_value = {
            "ResponseMetadata": {"HTTPStatusCode": 200},
            "Errors": [{"Key": "meter-photo.jpg", "Code": "AccessDenied"}],
        }
        with patch.dict(
            os.environ,
            {
                "FUEL_PHOTO_STORAGE": "r2",
                "R2_BUCKET_NAME": "private-meter-photos",
            },
        ), patch.object(
            photo_storage, "_r2_client", return_value=fake_client
        ):
            with self.assertRaises(PhotoStorageError):
                photo_storage.delete_photos(["meter-photo.jpg"])


if __name__ == "__main__":
    unittest.main()

from django.conf import settings
from django.core.files.storage import FileSystemStorage

try:
    from storages.backends.s3boto import S3BotoStorage
except ImportError:
    S3BotoStorage = None

S3_STATIC_BUCKET = getattr(settings, "S3_STATIC_BUCKET", None)


class KegbotFileSystemStorage(FileSystemStorage):
    """Default storage backend for Kegbot media files.

    Uses MEDIA_URL directly so generated URLs are host-relative (e.g.
    /media/pics/foo.jpg).  The old approach of prepending an absolute
    base URL via get_base_url() mutated shared instance state on the
    first request, permanently locking in whatever hostname hit first
    (typically localhost from the kiosk) for all subsequent requests.
    Absolute URLs for notifications are constructed explicitly by
    KegbotSite.base_url(), not here.
    """


if S3BotoStorage:

    class S3StaticStorage(S3BotoStorage):
        """Uses settings.S3_STATIC_BUCKET instead of AWS_STORAGE_BUCKET_NAME."""

        def __init__(self, *args, **kwargs):
            kwargs["bucket"] = S3_STATIC_BUCKET
            super(S3StaticStorage, self).__init__(*args, **kwargs)

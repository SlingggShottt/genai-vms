"""S3-compatible object storage: client + s3:// URI helpers.

See design_architecture.md §6.3 for the bucket layout.
"""

from vms_common.storage.s3 import S3Client
from vms_common.storage.uri import InvalidS3UriError, S3Location, build_uri, parse_uri

__all__ = ["InvalidS3UriError", "S3Client", "S3Location", "build_uri", "parse_uri"]

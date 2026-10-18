"""Install a memory-only upload cap before CSRF reads this route's multipart body."""

from io import BytesIO

from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.files.uploadhandler import FileUploadHandler, StopUpload

from portfolios.holdings_csv import MAX_CSV_BYTES

PREVIEW_PATH = "/portfolios/check-holdings/"


class BoundedHoldingsUpload(FileUploadHandler):
    chunk_size = 4096

    def __init__(self, request):
        super().__init__(request)
        self.count = 0
        self.received = 0
        self.error = ""

    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self.count += 1
        if self.count != 1 or self.field_name != "holdings_file":
            self.error = "Upload exactly one holdings CSV."
            raise StopUpload(connection_reset=True)
        self.file = BytesIO()

    def receive_data_chunk(self, raw_data, start):
        self.received += len(raw_data)
        if self.received > MAX_CSV_BYTES:
            self.error = "Use a CSV no larger than 16 KiB."
            raise StopUpload(connection_reset=True)
        self.file.write(raw_data)
        return None

    def file_complete(self, file_size):
        self.file.seek(0)
        return InMemoryUploadedFile(
            self.file, self.field_name, self.file_name, self.content_type, file_size, self.charset
        )

    def upload_interrupted(self):
        if hasattr(self, "file"):
            self.file.close()


class HoldingsUploadMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path_info == PREVIEW_PATH or request.path_info.startswith(
            "/portfolios/snapshots/"
        ):
            request.sensitive_post_parameters = "__ALL__"
        if request.path_info == PREVIEW_PATH:
            handler = BoundedHoldingsUpload(request)
            request.holdings_upload = handler
            # No temporary-file fallback, even for forged sizes or extra files.
            request.upload_handlers = [handler]
        return self.get_response(request)

from unittest.mock import MagicMock, patch


def test_upload_bytes_calls_put_object():
    with patch("shared.s3.boto3.client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        from shared.s3 import upload_bytes

        upload_bytes("my-bucket", "key/file.png", b"data", "image/png")
    mock_client.put_object.assert_called_once()
    call_kwargs = mock_client.put_object.call_args.kwargs
    assert call_kwargs["Bucket"] == "my-bucket"
    assert call_kwargs["Key"] == "key/file.png"
    assert call_kwargs["Body"] == b"data"
    assert call_kwargs["ContentType"] == "image/png"


def test_upload_file_calls_upload():
    with patch("shared.s3.boto3.client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        from shared.s3 import upload_file

        upload_file("my-bucket", "key/file.mp4", "/tmp/file.mp4", "video/mp4")
    assert mock_client.upload_file.called or mock_client.put_object.called


def test_generate_presigned_url_returns_string():
    with patch("shared.s3.boto3.client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_client.generate_presigned_url.return_value = "https://presigned.example"
        from shared.s3 import generate_presigned_url

        result = generate_presigned_url("my-bucket", "key/file.mp3")
    assert result == "https://presigned.example"


def test_generate_presigned_url_default_expiry():
    with patch("shared.s3.boto3.client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        mock_client.generate_presigned_url.return_value = "https://url"
        from shared.s3 import generate_presigned_url

        generate_presigned_url("my-bucket", "key/file.mp3")
    call_kwargs = mock_client.generate_presigned_url.call_args.kwargs
    assert call_kwargs.get("ExpiresIn", 3600) == 3600


def test_download_file_calls_download():
    with patch("shared.s3.boto3.client") as mock_client_factory:
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client
        from shared.s3 import download_file

        download_file("my-bucket", "key/file.mp3", "/tmp/file.mp3")
    assert mock_client.download_file.called
    call_args = mock_client.download_file.call_args
    assert "my-bucket" in str(call_args)
    assert "key/file.mp3" in str(call_args)

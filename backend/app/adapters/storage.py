"""Armazenamento de objetos. Regras de negócio só conhecem `StorageAdapter`.

Chaves são aleatórias e organizadas por workspace: `w/<workspace>/<área>/<uuid>.<ext>`.
Nenhum nome de arquivo enviado pelo usuário é usado como caminho.
"""

from __future__ import annotations

import io
import shutil
import tempfile
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from app.core.config import get_settings
from app.core.errors import TransientError


class StorageAdapter(Protocol):
    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...
    def put_file(self, key: str, path: Path, content_type: str = "application/octet-stream") -> None: ...
    def get(self, key: str) -> bytes: ...
    def stream(self, key: str, chunk_size: int = 1024 * 256) -> Iterator[bytes]: ...
    def delete(self, key: str) -> None: ...
    def exists(self, key: str) -> bool: ...


class StorageError(TransientError):
    pass


class LocalStorage:
    """Apenas para desenvolvimento/testes sem Docker. Produção usa S3/MinIO."""

    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents and p != self.root:
            raise ValueError("Chave de armazenamento inválida.")
        return p

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(p)

    def put_file(self, key: str, path: Path, content_type: str = "application/octet-stream") -> None:
        p = self._path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, p)

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError as exc:
            raise StorageError(f"Objeto não encontrado: {key}") from exc

    def stream(self, key: str, chunk_size: int = 1024 * 256) -> Iterator[bytes]:
        try:
            with self._path(key).open("rb") as fh:
                while chunk := fh.read(chunk_size):
                    yield chunk
        except FileNotFoundError as exc:
            raise StorageError(f"Objeto não encontrado: {key}") from exc

    def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    def exists(self, key: str) -> bool:
        return self._path(key).exists()


class S3Storage:
    def __init__(self) -> None:
        import boto3
        from botocore.config import Config

        s = get_settings()
        self.bucket = s.s3_bucket
        self.sse = s.s3_sse
        self.client = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint_url,
            aws_access_key_id=s.s3_access_key,
            aws_secret_access_key=s.s3_secret_key,
            region_name=s.s3_region,
            config=Config(
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5,
                read_timeout=60,
                s3={"addressing_style": "path"},
            ),
        )
        if s.s3_create_bucket:
            self._ensure_bucket()

    def _ensure_bucket(self, attempts: int = 30) -> None:
        """Cria o bucket se preciso, aguardando o serviço S3 ficar disponível (subida paralela no compose)."""
        import time

        from botocore.exceptions import BotoCoreError, ClientError

        for attempt in range(attempts):
            try:
                try:
                    self.client.head_bucket(Bucket=self.bucket)
                except ClientError:
                    try:
                        self.client.create_bucket(Bucket=self.bucket)
                    except ClientError as exc:  # corrida entre processos: bucket já criado
                        if exc.response.get("Error", {}).get("Code") not in (
                            "BucketAlreadyOwnedByYou",
                            "BucketAlreadyExists",
                        ):
                            raise
                return
            except BotoCoreError:
                if attempt == attempts - 1:
                    raise
                time.sleep(1)

    def _extra(self, content_type: str) -> dict[str, Any]:
        extra: dict[str, Any] = {"ContentType": content_type}
        if self.sse:
            extra["ServerSideEncryption"] = "AES256"
        return extra

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            self.client.put_object(Bucket=self.bucket, Key=key, Body=data, **self._extra(content_type))
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"Falha ao gravar no armazenamento: {type(exc).__name__}") from exc

    def put_file(self, key: str, path: Path, content_type: str = "application/octet-stream") -> None:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            self.client.upload_file(str(path), self.bucket, key, ExtraArgs=self._extra(content_type))
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"Falha ao enviar arquivo: {type(exc).__name__}") from exc

    def get(self, key: str) -> bytes:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"Falha ao ler do armazenamento: {type(exc).__name__}") from exc

    def stream(self, key: str, chunk_size: int = 1024 * 256) -> Iterator[bytes]:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"Falha ao ler do armazenamento: {type(exc).__name__}") from exc
        try:
            yield from body.iter_chunks(chunk_size)
        finally:
            body.close()

    def delete(self, key: str) -> None:
        from botocore.exceptions import BotoCoreError, ClientError

        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(f"Falha ao remover objeto: {type(exc).__name__}") from exc

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False


@lru_cache
def get_storage() -> StorageAdapter:
    s = get_settings()
    if s.storage_backend == "s3":
        return S3Storage()
    return LocalStorage(s.local_storage_dir)


def reset_storage() -> None:
    get_storage.cache_clear()


def scratch_dir(prefix: str = "minuta-") -> Path:
    return Path(tempfile.mkdtemp(prefix=prefix))


def memory_file(data: bytes) -> io.BytesIO:
    return io.BytesIO(data)

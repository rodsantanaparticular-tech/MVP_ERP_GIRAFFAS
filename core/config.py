import base64
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict


def _ler_segredo(caminho: str | None, nome: str) -> str:
    if not caminho or not Path(caminho).is_file():
        raise RuntimeError(f"segredo '{nome}' não encontrado (arquivo: {caminho!r})")
    valor = Path(caminho).read_text(encoding="utf-8").strip()
    if not valor:
        raise RuntimeError(f"segredo '{nome}' está vazio (arquivo: {caminho!r})")
    return valor


class Settings(BaseSettings):
    """Configuração não secreta vem do ambiente; segredos vêm de arquivos
    (Docker secrets em /run/secrets), nunca de variável de ambiente."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "producao"

    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "erp"
    # dono do schema: só migrações e CLI administrativa
    postgres_user: str = "erp"
    postgres_password_file: str | None = None
    # papel da aplicação: sem superusuário, sujeito a Row-Level Security
    app_db_user: str = "erp_app"
    app_db_password_file: str | None = None

    jwt_secret_file: str | None = None
    jwt_expire_minutes: int = 480

    erp_master_key_file: str | None = None
    erp_master_key_version: int = 1

    login_max_falhas: int = 10
    login_janela_minutos: int = 15
    senha_min_caracteres: int = 8

    def _url(self, usuario: str, senha: str) -> str:
        return (f"postgresql+psycopg://{quote(usuario)}:{quote(senha, safe='')}"
                f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}")

    @property
    def database_url(self) -> str:
        return self._url(self.app_db_user, _ler_segredo(self.app_db_password_file, "app_db_password"))

    @property
    def migrations_database_url(self) -> str:
        return self._url(self.postgres_user, _ler_segredo(self.postgres_password_file, "postgres_password"))


settings = Settings()


@lru_cache
def jwt_secret() -> str:
    return _ler_segredo(settings.jwt_secret_file, "jwt_secret")


@lru_cache
def master_key() -> bytes:
    chave = base64.b64decode(_ler_segredo(settings.erp_master_key_file, "erp_master_key"))
    if len(chave) != 32:
        raise RuntimeError("erp_master_key precisa ter 32 bytes (base64)")
    return chave

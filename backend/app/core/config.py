"""Configuração centralizada. Tudo vem de variáveis de ambiente (ver .env.example)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DEFAULT_LIMITS: dict[str, int] = {
    "max_generators": 200,
    "max_batch_rows": 1000,
    "max_upload_mb": 15,
    "max_docs_per_month": 20000,
    "max_fields_per_generator": 200,
    "max_kits": 100,
    "max_generators_per_kit": 20,
    "max_kit_fields": 100,
    # ações com IA externa por mês (marcar campos, preencher por texto, revisar). Com cobrança ligada vem do plano.
    "max_ai_actions_per_month": 200,
}


def _secret(value: str | None, path: str | None) -> str | None:
    """Segredo pela variável ou pelo arquivo (secret do Docker). Arquivo ilegível/vazio = não configurado."""
    if value:
        return value
    if path:
        try:
            return Path(path).read_text(encoding="utf-8").strip() or None
        except OSError:
            return None
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "DocFeito"
    app_env: Literal["development", "test", "production"] = "development"
    secret_key: str = Field(default="dev-only-change-me-please-32-bytes-min")
    public_web_url: str = "http://localhost:3000"
    # NoDecode: aceita "a,b,c" no ambiente (senão o pydantic-settings exige JSON e a API nem sobe)
    allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    # Banco
    database_url: str = "sqlite:///./data/dev.db"
    db_pool_size: int = 10

    # Fila
    redis_url: str | None = None
    job_backend: Literal["sync", "thread", "dramatiq"] = "thread"
    job_max_retries: int = 3
    job_time_limit_ms: int = 60 * 60 * 1000
    worker_metrics_port: int = 9191
    # Recuperação após queda do worker (não depende do redelivery probabilístico do broker):
    # o executor renova o heartbeat a cada `job_heartbeat_seconds`; job 'processing' sem heartbeat há
    # `job_stale_seconds` é retomado pelo watchdog (mantenha stale >= 3x o heartbeat); job 'queued' sem ser
    # assumido por `job_queue_grace_seconds` (mensagem perdida) também é reenfileirado.
    job_heartbeat_seconds: int = 10
    job_stale_seconds: int = 60
    job_queue_grace_seconds: int = 300
    watchdog_interval_seconds: int = 15

    # Armazenamento
    storage_backend: Literal["local", "s3"] = "local"
    local_storage_dir: str = "./data/storage"
    s3_endpoint_url: str | None = None
    s3_bucket: str = "minuta"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str = "us-east-1"
    s3_create_bucket: bool = True
    s3_sse: bool = False  # criptografia em repouso no S3 (SSE-S3)

    # PDF
    pdf_converter: Literal["libreoffice", "none"] = "libreoffice"
    soffice_path: str = "soffice"
    pdf_timeout_seconds: int = 120
    pdf_chunk_size: int = 20
    # Importar PDF digitado como modelo (docx_engine.pdf_import). Desligado por padrão no código. Em produção só vale
    # com o conversor isolado (serviço `pdfconv`, D35: contêiner sem rede de saída e sem segredos) em
    # PDF_CONVERTER_URL; sem ele o PDF continua recusado. Fora de produção, sem URL, converte num processo filho local.
    pdf_import_enabled: bool = False
    pdf_converter_url: str | None = None

    # IA
    # Trava geral de serviços externos de IA (Anthropic e TypeSafe/Jev). Desligada por padrão (piloto): mesmo com
    # AI_PROVIDER=anthropic/auto e chaves configuradas, nada sai do servidor; valem só regras e heurísticas locais.
    external_ai_enabled: bool = False
    # Métricas de ativação agregadas (D32): opt-in. Desligadas, nada é calculado nem gravado.
    activation_metrics_enabled: bool = False
    ai_provider: Literal["auto", "local", "anthropic", "openrouter", "none"] = "auto"
    # OpenRouter (D33): uma chave dá acesso a vários modelos; o modelo foi escolhido medindo no conjunto ouro
    # (docs/ai/avaliacao-modelos.md). Chave pela variável OU por arquivo (segredo do Docker em /run/secrets).
    openrouter_api_key: str | None = None
    openrouter_key_file: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # análise do documento enviado (roda no worker, uma vez por modelo): melhor recall/precisão por custo
    openrouter_model: str = "anthropic/claude-haiku-5.5"
    # "preencher com IA" e "revisar com IA": a pessoa espera na tela, então pesa a latência (≈2–3 s) além do acerto
    openrouter_assist_model: str = "google/gemini-2.5-flash"
    # Tetos de custo da IA externa (app.modules.ai_budget): por chamada e no mês, somando todos os workspaces.
    # A cota por workspace vem do plano (max_ai_actions_per_month).
    ai_max_call_usd: float = 0.05
    ai_monthly_budget_usd: float = 20.0
    ai_api_key: str | None = None
    ai_base_url: str = "https://api.anthropic.com"
    ai_model: str = "claude-haiku-4-5-20251001"
    ai_timeout_seconds: float = 30.0
    ai_max_retries: int = 2
    ai_max_chars: int = 60_000

    # Classificação semântica de papéis para o auto-detect de kits (opcional; ver docs/DECISIONS.md D24).
    # Sem chave, o auto-detect usa só a heurística local por similaridade de rótulo.
    typesafe_api_key: str | None = None
    typesafe_base_url: str = "https://api.typesafe.ai"
    typesafe_model: str = "jev-latest"
    typesafe_timeout_seconds: float = 12.0

    # Cobrança (Stripe; docs/PAGAMENTOS.md). Desligada: valem os limites padrão (DEFAULT_LIMITS) e não há checkout.
    # Ligada: cada workspace segue os limites do plano (Grátis sem assinatura).
    billing_enabled: bool = False
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    # alternativa às variáveis acima: arquivo com o segredo (secret do Docker em /run/secrets; docker-compose.billing.yml)
    stripe_secret_key_file: str | None = None
    stripe_webhook_secret_file: str | None = None
    # configuração do portal do cliente criada por scripts/stripe_setup.py (bpc_…); vazio = a padrão da conta
    stripe_portal_configuration: str | None = None
    # configuração de formas de pagamento só com Pix (pmc_…), para o checkout "Pagar com Pix"; vazio = as do painel
    stripe_pix_payment_method_configuration: str | None = None
    stripe_price_profissional_mensal: str | None = None
    stripe_price_profissional_anual: str | None = None
    stripe_price_escritorio_mensal: str | None = None
    stripe_price_escritorio_anual: str | None = None
    # Pix na Stripe Brasil é liberado sob convite: ligue só depois de ver "Pix" ativo no painel da Stripe.
    billing_pix_enabled: bool = False

    # Sessão / segurança
    cookie_secure: bool = False
    cookie_domain: str | None = None
    session_ttl_hours: int = 24 * 14
    password_reset_ttl_minutes: int = 60
    download_token_ttl_seconds: int = 300
    file_retention_days: int = 7
    max_upload_mb: int = 15
    login_rate_limit_per_minute: int = 20

    # Limites padrão por workspace (sobrescritos por workspaces.limits)
    default_limits: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_LIMITS))

    log_level: str = "INFO"
    log_json: bool = True
    seed_demo_password: str = "demo12345"

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def stripe_api_key(self) -> str | None:
        return _secret(self.stripe_secret_key, self.stripe_secret_key_file)

    @property
    def stripe_webhook_signing_secret(self) -> str | None:
        return _secret(self.stripe_webhook_secret, self.stripe_webhook_secret_file)

    @property
    def pdf_import_mode(self) -> Literal["service", "process", "off"]:
        """service = conversor isolado (D35); process = processo filho local (só fora de produção); off = recusa."""
        if not self.pdf_import_enabled:
            return "off"
        if self.pdf_converter_url:
            return "service"
        return "off" if self.is_production else "process"

    def validate_for_production(self) -> None:
        if not self.is_production:
            return
        problems = []
        if self.secret_key.startswith("dev-only"):
            problems.append("SECRET_KEY padrão em produção")
        if not self.cookie_secure:
            problems.append("COOKIE_SECURE deve ser true em produção")
        if problems:
            raise RuntimeError("Configuração insegura: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()

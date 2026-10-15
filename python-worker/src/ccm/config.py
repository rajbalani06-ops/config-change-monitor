from __future__ import annotations

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    service_name: str = "ccm-worker"
    schema_version: str = "1.0"

    database_url: str = "postgresql://ccm:ccm@localhost:5432/ccm"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "ccm"
    postgres_user: str = "ccm"
    postgres_password: str = "ccm"

    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "ccm"
    rabbitmq_password: str = "ccm"
    rabbitmq_vhost: str = "/"
    rabbitmq_exchange: str = "ccm.events"
    rabbitmq_queue: str = "ccm.notifications"
    rabbitmq_dlq: str = "ccm.notifications.dlq"

    redis_enabled: bool = False
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str = ""
    redis_ttl_seconds: int = 3600

    watch_allowlist: str = "/watched"
    emit_initial_snapshot_events: bool = False
    debounce_ms: int = 400
    stable_file_ms: int = 250
    watcher_lease_seconds: int = 15
    watcher_concurrency: int = 32
    poll_fallback_seconds: int = 30
    worker_id: str = ""

    webhook_timeout_seconds: float = 5.0
    webhook_max_retries: int = 5
    webhook_base_backoff_ms: int = 500
    webhook_max_backoff_ms: int = 30000
    webhook_allow_private_networks: bool = False
    circuit_failure_threshold: int = 5
    circuit_open_seconds: int = 30
    consumer_prefetch: int = 16

    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    otel_service_name: str = "ccm-worker"
    metrics_port: int = 9100

    redaction_key_patterns: str = (
        "password,secret,token,api[_-]?key,credential,"
        "connection[_-]?string,private[_-]?key,passwd,auth"
    )
    default_tenant_id: str = "default"

    def allowlisted_roots(self) -> list[str]:
        return [p.strip() for p in self.watch_allowlist.split(";") if p.strip()]

    def redaction_patterns(self) -> list[str]:
        return [p.strip() for p in self.redaction_key_patterns.split(",") if p.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

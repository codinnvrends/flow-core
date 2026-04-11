from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # PostgreSQL
    pg_host: str = "postgres"
    pg_port: int = 5432
    pg_user: str = "flowcore"
    pg_password: str = "flowcore_secret"
    pg_db: str = "flowcore"

    # TimescaleDB
    ts_host: str = "timescaledb"
    ts_port: int = 5432
    ts_user: str = "flowcore"
    ts_password: str = "flowcore_secret"
    ts_db: str = "flowcore_ts"

    # Neo4j
    neo4j_host: str = "neo4j"
    neo4j_bolt_port: int = 7687
    neo4j_user: str = "neo4j"
    neo4j_password: str = "flowcore_secret"

    # Kafka
    kafka_bootstrap_servers: str = "kafka:9092"

    # MLflow
    mlflow_tracking_uri: str = "http://agents:5000"

    # Service-specific
    log_level: str = "info"
    service_name: str = "flowcore-service"

    @property
    def pg_dsn(self) -> str:
        return f"postgresql://{self.pg_user}:{self.pg_password}@{self.pg_host}:{self.pg_port}/{self.pg_db}"

    @property
    def ts_dsn(self) -> str:
        return f"postgresql://{self.ts_user}:{self.ts_password}@{self.ts_host}:{self.ts_port}/{self.ts_db}"

    @property
    def neo4j_uri(self) -> str:
        return f"bolt://{self.neo4j_host}:{self.neo4j_bolt_port}"

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()

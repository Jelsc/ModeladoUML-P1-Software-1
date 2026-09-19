from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DB_URL: str = "sqlite:///./uml.db"
    REDIS_URL: str = "redis://localhost:6379/0"
    JWT_SECRET: str = "change-me"
    CORS_ORIGINS: str = "http://localhost:8090"
    SEED_DEMO: bool = False
    DEPLOY_NETWORK: str = "primer-parcial-sw1_uml-generated"
    DEPLOY_BUILD_DIR: str = "/deploy-build"
    DEPLOY_GATEWAY_CONFIG_DIR: str = "/deploy-gateway"
    DEPLOY_GATEWAY_CONTAINER: str = "primer-parcial-sw1-deploy-gateway-1"
    DEPLOY_GATEWAY_PORT: int = 80
    DEPLOY_BUILD_TIMEOUT: int = 600
    DEPLOY_CREDENTIAL_SECRET: str | None = None
    WHISPER_MODEL: str = "base"
    WHISPER_DEVICE: str = "cpu"
    WHISPER_COMPUTE_TYPE: str = "int8"
    GEMINI_API_KEY: str | None = None

    class Config:
        env_file = ".env"
        env_ignore_empty = True
        extra = "ignore"

settings = Settings()

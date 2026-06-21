from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env")

    mongodb_uri: str = "mongodb://mongo:27017"
    mongodb_db: str = "ai_data_store"
    api_key: str


settings = Settings()

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    mongodb_uri: str = "mongodb://mongo:27017"
    mongodb_db: str = "ai_data_store"
    api_key: str

    class Config:
        env_file = ".env"


settings = Settings()

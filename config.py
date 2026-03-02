class Config:
    SECRET_KEY = "dev-secret-key"
    SQLALCHEMY_DATABASE_URI = "sqlite:///devops.db"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
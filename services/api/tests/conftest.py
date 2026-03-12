import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker

# Import the FastAPI app and the database components
from api.main import app
from api.db import Base, get_db

# Use an in-memory SQLite database for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

# Create a new engine for testing, using StaticPool to keep the in-memory db alive across the session
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=pool.StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database for each test."""
    # Create the tables
    Base.metadata.create_all(bind=engine)
    
    session = TestingSessionLocal()
    yield session
    
    session.close()
    # Drop the tables after the test
    Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="function")
def client(db_session):
    """Create a test client that uses the test database."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    # Override the dependency to use our test database
    app.dependency_overrides[get_db] = override_get_db
    
    with TestClient(app) as c:
        yield c
        
    # Clear overrides after test
    app.dependency_overrides.clear()

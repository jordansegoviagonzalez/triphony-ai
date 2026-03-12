from fastapi.testclient import TestClient

def test_register_user(client: TestClient):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Test User",
            "email": "test@example.com",
            "password": "securepassword123"
        }
    )
    
    # Assert the response status is 200 OK
    assert response.status_code == 200
    data = response.json()
    
    # Assert a JWT token is returned
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    
    # Assert the user info is returned correctly (without password)
    assert data["user"]["email"] == "test@example.com"
    assert data["user"]["name"] == "Test User"
    assert "id" in data["user"]
    assert "password" not in data["user"]
    assert "hashed_password" not in data["user"]


def test_register_duplicate_email(client: TestClient):
    # Register the first time
    client.post(
        "/api/v1/auth/register",
        json={"name": "Test User", "email": "test@example.com", "password": "securepassword123"}
    )
    
    # Try to register again with the same email
    response = client.post(
        "/api/v1/auth/register",
        json={"name": "Another User", "email": "test@example.com", "password": "differentpassword"}
    )
    
    # Assert the system blocks it with a 400 error
    assert response.status_code == 400
    assert response.json()["detail"] == "Email already registered"


def test_login_success(client: TestClient):
    # Setup: Create a user first
    client.post(
        "/api/v1/auth/register",
        json={"name": "Login Tester", "email": "login@example.com", "password": "mypassword"}
    )
    
    # Act: Attempt to log in (using Form data, which OAuth2PasswordRequestForm expects)
    response = client.post(
        "/api/v1/auth/login",
        data={"username": "login@example.com", "password": "mypassword"}
    )
    
    # Assert
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client: TestClient):
    # Setup
    client.post(
        "/api/v1/auth/register",
        json={"name": "Login Tester", "email": "login@example.com", "password": "mypassword"}
    )
    
    # Act: Login with wrong password
    response = client.post(
        "/api/v1/auth/login",
        data={"username": "login@example.com", "password": "WRONG_PASSWORD"}
    )
    
    # Assert
    assert response.status_code == 401
    assert response.json()["detail"] == "Incorrect email or password"

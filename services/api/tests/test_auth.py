from fastapi.testclient import TestClient


def _csrf_headers(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("triphony_csrf")}

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
    
    # The session is delivered only in the HttpOnly cookie.
    assert "access_token" not in data
    assert "token_type" not in data
    
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
    assert "access_token" not in data
    assert "token_type" not in data


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


def test_cookie_session_current_user_and_logout(client: TestClient):
    registered = client.post(
        "/api/v1/auth/register",
        json={"name": "Cookie User", "email": "cookie@example.com", "password": "securepassword123"},
    )
    assert registered.status_code == 200
    assert "triphony_session=" in registered.headers["set-cookie"]

    current = client.get("/api/v1/auth/me")
    assert current.status_code == 200
    assert current.json()["email"] == "cookie@example.com"

    logged_out = client.post("/api/v1/auth/logout", headers=_csrf_headers(client))
    assert logged_out.status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 401

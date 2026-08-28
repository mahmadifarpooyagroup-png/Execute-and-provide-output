import os
import tempfile
from fastapi.testclient import TestClient
from atrin_core.security import LocalSecurityManager

def get_test_app(token_file_path: str):
    """Create a test app with custom token file path"""
    from fastapi import FastAPI, Depends, HTTPException, Header
    from typing import Optional
    
    app = FastAPI(title="Atrin Local Control Plane", version="0.1.0")
    
    def get_security_manager() -> LocalSecurityManager:
        return LocalSecurityManager(token_file_path=token_file_path)
    
    def require_auth(
        x_atrin_token: Optional[str] = Header(None), 
        security: LocalSecurityManager = Depends(get_security_manager)
    ):
        if not x_atrin_token or not security.validate_token(x_atrin_token):
            raise HTTPException(status_code=401, detail="Invalid or missing Atrin runtime token")
        return True
    
    @app.get("/health")
    async def health_check():
        return {"status": "healthy", "service": "atrin-control-plane"}
    
    @app.get("/api/v1/status")
    async def get_status(authenticated: bool = Depends(require_auth)):
        return {"status": "operational", "message": "Local runtime is secure and running"}
    
    return app

def test_health_endpoint_public():
    from atrin_core.runtime import app
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_status_endpoint_requires_auth():
    from atrin_core.runtime import app
    client = TestClient(app)
    response = client.get("/api/v1/status")
    assert response.status_code == 401

def test_status_endpoint_with_valid_token():
    with tempfile.TemporaryDirectory() as tmpdir:
        token_file = os.path.join(tmpdir, "test.token")
        security = LocalSecurityManager(token_file_path=token_file)
        valid_token = security.get_or_create_token()
        
        app = get_test_app(token_file_path=token_file)
        client = TestClient(app)
        
        response = client.get("/api/v1/status", headers={"X-Atrin-Token": valid_token})
        assert response.status_code == 200
        assert response.json()["status"] == "operational"

def test_status_endpoint_with_invalid_token():
    from atrin_core.runtime import app
    client = TestClient(app)
    response = client.get("/api/v1/status", headers={"X-Atrin-Token": "wrong_token"})
    assert response.status_code == 401

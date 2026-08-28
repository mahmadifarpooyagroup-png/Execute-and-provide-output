import uvicorn
from fastapi import FastAPI, Depends, HTTPException, Header
from typing import Optional
from .security import LocalSecurityManager
from .database import AtrinDatabase
import os

app = FastAPI(title="Atrin Local Control Plane", version="0.1.0")

# Dependency for token validation
def get_security_manager(token_file_path: str = ".atrin_data/runtime_secret.token") -> LocalSecurityManager:
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

def start_runtime(host: str = "127.0.0.1", port: int = 8765):
    # بخش ۴۰: هرگز روی 0.0.0.0 اجرا نشود
    print(f"Starting Atrin Runtime on http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")

import os
import platform
from typing import Optional


def get_browser_profile_path(provider_id: str, profile_id: str) -> str:
    """
    Generate a secure browser profile path based on the operating system.
    
    According to Spec Section 17, these paths must never be inside the git repository.
    
    For Windows: %LOCALAPPDATA%\Atrin\BrowserProfiles\{provider_id}_{profile_id}
    For Linux/WSL: ~/.local/share/Atrin/BrowserProfiles/{provider_id}_{profile_id}
    
    Args:
        provider_id: The provider identifier (e.g., 'qwen', 'claude')
        profile_id: The unique profile identifier
        
    Returns:
        Absolute path to the browser profile directory
    """
    system = platform.system()
    
    if system == "Windows":
        # Windows: Use LOCALAPPDATA
        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            # Fallback if LOCALAPPDATA is not set
            local_app_data = os.path.expanduser("~\\AppData\\Local")
        
        base_path = os.path.join(local_app_data, "Atrin", "BrowserProfiles")
    else:
        # Linux/WSL/macOS: Use ~/.local/share/Atrin/BrowserProfiles
        home_dir = os.path.expanduser("~")
        base_path = os.path.join(home_dir, ".local", "share", "Atrin", "BrowserProfiles")
    
    # Create the profile-specific subdirectory name
    profile_dir_name = f"{provider_id}_{profile_id}"
    
    # Full path
    full_path = os.path.join(base_path, profile_dir_name)
    
    # Ensure the directory exists
    os.makedirs(full_path, exist_ok=True)
    
    return full_path

import os
import platform

def get_browser_profile_path(provider_id: str, profile_id: str) -> str:
    system = platform.system()
    if system == "Windows":
        base_dir = os.environ.get("LOCALAPPDATA") or os.path.expanduser(r"~\AppData\Local")
        base_dir = os.path.join(base_dir, "Atrin", "BrowserProfiles")
    else:
        base_dir = os.environ.get(
            "ATRIN_BROWSER_PROFILES_DIR",
            os.path.expanduser("~/.local/share/Atrin/BrowserProfiles"),
        )

    profile_dir = os.path.join(base_dir, f"{provider_id}_{profile_id}")
    os.makedirs(profile_dir, exist_ok=True)

    if system != "Windows":
        os.chmod(profile_dir, 0o700)
    return profile_dir

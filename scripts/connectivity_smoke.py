from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    required = {
        "MTEAM_BASE_URL": settings.mteam_base_url,
        "MTEAM_API_KEY": settings.mteam_api_key,
        "QB_BASE_URL": settings.qb_base_url,
        "QB_USERNAME": settings.qb_username,
        "QB_PASSWORD": settings.qb_password,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise SystemExit(f"Missing required connectivity settings: {', '.join(missing)}")
    print("Connectivity settings present. Ready for real-environment spike.")


if __name__ == "__main__":
    main()

from dataclasses import dataclass


@dataclass(slots=True)
class QBittorrentAdapter:
    base_url: str
    username: str
    password: str
    timeout_seconds: float = 10.0

    def _normalized_base_url(self) -> str:
        return self.base_url.rstrip("/")

    def login_endpoint(self) -> str:
        return f"{self._normalized_base_url()}/api/v2/auth/login"

    def add_torrent_endpoint(self) -> str:
        return f"{self._normalized_base_url()}/api/v2/torrents/add"

    def categories_endpoint(self) -> str:
        return f"{self._normalized_base_url()}/api/v2/torrents/categories"

    def build_login_payload(self) -> dict[str, str]:
        return {"username": self.username, "password": self.password}

    def build_add_payload(
        self,
        url: str,
        category: str,
        rename: str,
        paused: bool = False,
        tags: list[str] | None = None,
    ) -> dict[str, str]:
        clean_url = url.strip()
        clean_category = category.strip()
        clean_rename = rename.strip()
        if not clean_url:
            raise ValueError("url must not be empty")
        if not clean_category:
            raise ValueError("category must not be empty")
        if not clean_rename:
            raise ValueError("rename must not be empty")

        payload: dict[str, str] = {
            "urls": clean_url,
            "category": clean_category,
            "rename": clean_rename,
            "paused": "true" if paused else "false",
        }
        if tags:
            payload["tags"] = ",".join(tag.strip() for tag in tags if tag.strip())
        return payload

    async def login(self) -> None:
        raise NotImplementedError("Task 4 skeleton: real HTTP login wiring will be added later.")

    async def list_categories(self) -> dict:
        raise NotImplementedError(
            "Task 4 skeleton: real HTTP category listing wiring will be added later."
        )

    async def add_torrent_url(
        self,
        url: str,
        category: str,
        rename: str,
        paused: bool = False,
        tags: list[str] | None = None,
    ) -> dict:
        raise NotImplementedError("Task 4 skeleton: real HTTP add wiring will be added later.")

from dataclasses import dataclass


@dataclass(slots=True)
class MTeamAdapter:
    base_url: str
    api_key: str
    timeout_seconds: float = 10.0

    def _normalized_base_url(self) -> str:
        return self.base_url.rstrip("/")

    def search_endpoint(self) -> str:
        return f"{self._normalized_base_url()}/api/torrent/search"

    def detail_endpoint(self) -> str:
        return f"{self._normalized_base_url()}/api/torrent/detail"

    def download_token_endpoint(self) -> str:
        return f"{self._normalized_base_url()}/api/torrent/genDlToken"

    def build_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "content-type": "application/json",
        }

    def build_search_payload(
        self,
        keyword: str,
        page: int = 1,
        page_size: int = 20,
        categories: list[int] | None = None,
    ) -> dict:
        clean_keyword = keyword.strip()
        if not clean_keyword:
            raise ValueError("keyword must not be empty")
        if page < 1:
            raise ValueError("page must be >= 1")
        if page_size < 1:
            raise ValueError("page_size must be >= 1")
        return {
            "mode": "normal",
            "keyword": clean_keyword,
            "categories": categories or [],
            "pageNumber": page,
            "pageSize": page_size,
        }

    def build_detail_payload(self, torrent_id: str) -> dict[str, str]:
        if not torrent_id.strip():
            raise ValueError("torrent_id must not be empty")
        return {"id": torrent_id.strip()}

    def build_download_token_payload(self, torrent_id: str) -> dict[str, str]:
        if not torrent_id.strip():
            raise ValueError("torrent_id must not be empty")
        return {"id": torrent_id.strip()}

    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> list[dict]:
        raise NotImplementedError("Task 4 skeleton: real HTTP search wiring will be added later.")

    async def get_detail(self, torrent_id: str) -> dict:
        raise NotImplementedError("Task 4 skeleton: real HTTP detail wiring will be added later.")

    async def get_download_url(self, torrent_id: str) -> str:
        raise NotImplementedError(
            "Task 4 skeleton: real HTTP download token wiring will be added later."
        )

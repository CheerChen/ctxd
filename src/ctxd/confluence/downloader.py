"""Generic downloader helper (kept for compatibility/reuse)."""

from __future__ import annotations

import concurrent.futures
import os
from urllib.parse import urlparse

import requests


class ImageDownloader:
    def __init__(self, output_dir: str, max_workers: int = 5):
        self.output_dir = output_dir
        self.max_workers = max_workers
        self.session = requests.Session()

    def _generate_filename(self, url: str) -> str:
        parsed = urlparse(url)
        filename = os.path.basename(parsed.path) or f"image_{hash(url)}.png"
        return filename.split("?")[0]

    def _download_single(self, url: str) -> tuple[str, str | None]:
        try:
            filename = self._generate_filename(url)
            local_path = os.path.join(self.output_dir, filename)
            if os.path.exists(local_path):
                return url, local_path

            resp = self.session.get(url, timeout=10, stream=True)
            resp.raise_for_status()
            with open(local_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)
            return url, local_path
        except Exception:
            return url, None

    def download_images(self, urls: list[str]) -> dict[str, str]:
        if not urls:
            return {}
        os.makedirs(self.output_dir, exist_ok=True)
        image_map: dict[str, str] = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(self._download_single, u): u for u in urls}
            for future in concurrent.futures.as_completed(futures):
                downloaded_url, local_path = future.result()
                if local_path:
                    image_map[downloaded_url] = local_path

        return image_map

import logging
import os
import time

import requests

logger = logging.getLogger(__name__)

_MAX_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = (0.5, 1.0)


class JinaClient:
    def crawl(self, url: str, return_format: str = "html", timeout: int = 10) -> str:
        headers = {
            "Content-Type": "application/json",
            "X-Return-Format": return_format,
            "X-Timeout": str(timeout),
        }
        if os.getenv("JINA_API_KEY"):
            headers["Authorization"] = f"Bearer {os.getenv('JINA_API_KEY')}"
        else:
            logger.info("Jina API key is not set; unauthenticated requests are typically rejected. See https://jina.ai/reader for more information.")
        data = {"url": url}

        last_error = ""
        for attempt in range(_MAX_ATTEMPTS):
            if attempt > 0:
                time.sleep(_RETRY_BACKOFF_SECONDS[attempt - 1])
            result = self._post_once(url, headers, data, timeout)
            if not result.startswith("Error:"):
                return result
            if not _is_retryable(result):
                return result
            last_error = result
        return last_error or f"Error: Request to Jina API failed after {_MAX_ATTEMPTS} attempts"

    def _post_once(self, url: str, headers: dict, data: dict, timeout: int) -> str:
        try:
            # Enforce wall-clock limit: (connect, read) so hung connections don't block forever
            read_timeout = max(int(timeout), 5) + 3
            response = requests.post(
                "https://r.jina.ai/",
                headers=headers,
                json=data,
                timeout=(8, read_timeout),
            )

            if response.status_code != 200:
                error_message = f"Jina API returned status {response.status_code}: {response.text}"
                logger.error(error_message)
                return f"Error: {error_message}"

            if not response.text or not response.text.strip():
                error_message = "Jina API returned empty response"
                logger.error(error_message)
                return f"Error: {error_message}"

            return response.text
        except Exception as e:
            error_message = f"Request to Jina API failed: {str(e)}"
            logger.error(error_message)
            return f"Error: {error_message}"


def _is_retryable(error: str) -> bool:
    """Retry transient Jina-side failures; deterministic rejections are not retried."""
    if "status 429" in error or "status 500" in error or "status 502" in error or "status 503" in error or "status 504" in error:
        return True
    return "Request to Jina API failed" in error and "Read timed out" not in error

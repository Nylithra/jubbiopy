"""Kütüphane hata sınıfları."""

from __future__ import annotations


class JubbioError(Exception):
    """Tüm JubbioPy hatalarının temel sınıfı."""


class HTTPException(JubbioError):
    """REST API başarısız bir HTTP yanıtı döndürdüğünde fırlatılır."""

    def __init__(self, status: int, text: str, prefix: str = "API Error") -> None:
        self.status = status
        self.text = text
        super().__init__(f"{prefix} {status}: {text}")


class GatewayError(JubbioError):
    """Gateway bağlantısı kurulamadığında veya reddedildiğinde fırlatılır."""

    def __init__(self, message: str, code: int | None = None) -> None:
        self.code = code
        super().__init__(message)


class CollectorEnded(JubbioError):
    """Bir collector beklenen öğe gelmeden sona erdiğinde fırlatılır."""

    def __init__(self, reason: str | None, collected=None) -> None:
        self.reason = reason
        self.collected = collected
        super().__init__(f"Collector sona erdi: {reason}")

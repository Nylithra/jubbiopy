"""``Collection``: yardımcı metotlara sahip dict (JS ``Collection extends Map``)."""

from __future__ import annotations

import inspect
import random as _random
from typing import Any, Callable, Dict, Generic, Iterable, List, Optional, Tuple, TypeVar, Union

K = TypeVar("K")
V = TypeVar("V")
R = TypeVar("R")


class Collection(Dict[K, V], Generic[K, V]):
    """Ek yardımcı metotlarla genişletilmiş ``dict``.

    Fonksiyon parametreleri JS'deki gibi ``(value, key, collection)`` alır;
    daha az parametre alan fonksiyonlar (``lambda v: ...``) da desteklenir.
    """

    # ---------------------------------------------------------- Map uyumluluğu
    @property
    def cache(self) -> "Collection[K, V]":
        """Discord.js uyumluluğu — ``client.guilds.cache.get()`` çalışsın diye kendini döndürür."""
        return self

    @property
    def size(self) -> int:
        return len(self)

    def set(self, key: K, value: V) -> "Collection[K, V]":
        self[key] = value
        return self

    def has(self, key: K) -> bool:
        return key in self

    def delete(self, key: K) -> bool:
        return self.pop(key, _MISSING) is not _MISSING

    # ---------------------------------------------------------------- yardımcı
    @staticmethod
    def _call(fn: Callable[..., Any], *args: Any) -> Any:
        """``fn``'i kabul ettiği kadar argümanla çağırır (JS'deki gibi)."""
        return fn(*args[: _arity(fn, len(args))])

    def first(self, amount: Optional[int] = None) -> Union[Optional[V], List[V]]:
        values = list(self.values())
        if amount is None:
            return values[0] if values else None
        return values[:amount]

    def last(self, amount: Optional[int] = None) -> Union[Optional[V], List[V]]:
        values = list(self.values())
        if amount is None:
            return values[-1] if values else None
        return values[-amount:] if amount else []

    def first_key(self) -> Optional[K]:
        return next(iter(self), None)

    def random(self) -> Optional[V]:
        values = list(self.values())
        return _random.choice(values) if values else None

    def find(self, fn: Callable[..., bool]) -> Optional[V]:
        for key, value in self.items():
            if self._call(fn, value, key, self):
                return value
        return None

    def find_key(self, fn: Callable[..., bool]) -> Optional[K]:
        for key, value in self.items():
            if self._call(fn, value, key, self):
                return key
        return None

    def filter(self, fn: Callable[..., bool]) -> "Collection[K, V]":
        return Collection((k, v) for k, v in self.items() if self._call(fn, v, k, self))

    def map(self, fn: Callable[..., R]) -> List[R]:
        return [self._call(fn, v, k, self) for k, v in self.items()]

    def some(self, fn: Callable[..., bool]) -> bool:
        return any(self._call(fn, v, k, self) for k, v in self.items())

    def every(self, fn: Callable[..., bool]) -> bool:
        return all(self._call(fn, v, k, self) for k, v in self.items())

    def reduce(self, fn: Callable[..., R], initial: Any = None) -> R:
        acc = initial
        for key, value in self.items():
            acc = self._call(fn, acc, value, key, self)
        return acc

    def partition(self, fn: Callable[..., bool]) -> Tuple["Collection[K, V]", "Collection[K, V]"]:
        passed, failed = Collection(), Collection()
        for key, value in self.items():
            (passed if self._call(fn, value, key, self) else failed)[key] = value
        return passed, failed

    def sort(self, key: Optional[Callable[[V], Any]] = None, reverse: bool = False) -> "Collection[K, V]":
        items = sorted(self.items(), key=(lambda kv: key(kv[1])) if key else (lambda kv: kv[1]), reverse=reverse)
        return Collection(items)

    def to_array(self) -> List[V]:
        return list(self.values())

    def clone(self) -> "Collection[K, V]":
        return Collection(self)

    def concat(self, *collections: Iterable[Tuple[K, V]]) -> "Collection[K, V]":
        new = self.clone()
        for coll in collections:
            new.update(coll)
        return new

    def __repr__(self) -> str:
        return f"Collection({dict.__repr__(self)})"


def _arity(fn: Callable[..., Any], maximum: int) -> int:
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return maximum
    count = 0
    for param in params:
        if param.kind == param.VAR_POSITIONAL:
            return maximum
        if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD):
            count += 1
    return min(count, maximum)


class _Missing:
    pass


_MISSING = _Missing()

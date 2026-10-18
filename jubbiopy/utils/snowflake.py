"""Snowflake (ID) yardımcıları. Jubbio epoch: 2022-01-01T00:00:00.000Z."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Union

EPOCH = 1640995200000

Snowflake = Union[str, int]


@dataclass(frozen=True)
class DeconstructedSnowflake:
    timestamp: int
    worker_id: int
    process_id: int
    increment: int
    binary: str

    @property
    def date(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp / 1000, tz=timezone.utc)


class SnowflakeUtil:
    EPOCH = EPOCH

    @staticmethod
    def generate(timestamp: Union[int, float, datetime, None] = None) -> str:
        if timestamp is None:
            ms = int(time.time() * 1000)
        elif isinstance(timestamp, datetime):
            ms = int(timestamp.timestamp() * 1000)
        else:
            ms = int(timestamp)
        return str((ms - EPOCH) << 22)

    @staticmethod
    def deconstruct(snowflake: Snowflake) -> DeconstructedSnowflake:
        value = int(snowflake)
        return DeconstructedSnowflake(
            timestamp=(value >> 22) + EPOCH,
            worker_id=(value & 0x3E0000) >> 17,
            process_id=(value & 0x1F000) >> 12,
            increment=value & 0xFFF,
            binary=format(value, "064b"),
        )

    @staticmethod
    def timestamp_from(snowflake: Snowflake) -> int:
        return (int(snowflake) >> 22) + EPOCH

    @staticmethod
    def date_from(snowflake: Snowflake) -> datetime:
        return datetime.fromtimestamp(SnowflakeUtil.timestamp_from(snowflake) / 1000, tz=timezone.utc)

    @staticmethod
    def compare(a: Snowflake, b: Snowflake) -> int:
        x, y = int(a), int(b)
        return (x > y) - (x < y)

    @staticmethod
    def is_valid(value: object) -> bool:
        if not isinstance(value, str) or not value.isdigit() or not 17 <= len(value) <= 20:
            return False
        ts = SnowflakeUtil.timestamp_from(value)
        return EPOCH < ts < time.time() * 1000 + 1000 * 60 * 60 * 24 * 365

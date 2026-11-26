"""Stable named random streams for reproducible, independently mutable stems."""

from __future__ import annotations

import hashlib

import numpy as np


def derive_seed(root_seed: int | str, stream_name: str) -> int:
    """Derive a stable 64-bit seed without Python's process-randomized hash()."""
    payload = f"reawarp:v1:{root_seed}:{stream_name}".encode("utf-8")
    digest = hashlib.blake2b(payload, digest_size=8).digest()
    return int.from_bytes(digest, byteorder="little", signed=False)


class RandomStreams:
    """Provides one deterministic NumPy generator per named musical layer."""

    def __init__(
        self, root_seed: int | str, seed_overrides: dict[str, int] | None = None
    ) -> None:
        self.root_seed = root_seed
        self.seed_overrides = dict(seed_overrides or {})
        self._generators: dict[str, np.random.Generator] = {}

    def seed_for(self, name: str) -> int:
        return int(self.seed_overrides.get(name, derive_seed(self.root_seed, name)))

    def get(self, name: str) -> np.random.Generator:
        if name not in self._generators:
            self._generators[name] = np.random.default_rng(self.seed_for(name))
        return self._generators[name]

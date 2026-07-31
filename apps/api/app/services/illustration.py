from typing import Protocol

from app.config import settings


class IllustrationProvider(Protocol):
    def generate(
        self,
        *,
        avatar_seed: str,
        page_number: int,
        page_text: str,
    ) -> str: ...


class StubIllustrationProvider:
    def generate(
        self,
        *,
        avatar_seed: str,
        page_number: int,
        page_text: str,
    ) -> str:
        return (
            "https://picsum.photos/seed/"
            f"{avatar_seed}-{page_number}/640/480"
        )


_PROVIDERS: dict[str, IllustrationProvider] = {
    "stub": StubIllustrationProvider(),
}


def generate_illustration(
    *,
    avatar_seed: str,
    page_number: int,
    page_text: str,
) -> str:
    provider_name = settings.image_gen_provider.strip().lower()
    provider = _PROVIDERS.get(provider_name)
    if provider is None:
        raise ValueError(
            f"Unsupported illustration provider: {provider_name}"
        )

    return provider.generate(
        avatar_seed=avatar_seed,
        page_number=page_number,
        page_text=page_text,
    )

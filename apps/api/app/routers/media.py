from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Response

from app.schemas import StoryLanguage
from app.services.narration import generate_placeholder_wav
from app.services.narration_storage import read_narration_mp3


router = APIRouter(prefix="/media", tags=["media"])
NarrationToken = Annotated[str, Path(pattern=r"^[0-9a-f]{16}$")]
GeneratedNarrationToken = Annotated[
    str,
    Path(pattern=r"^[0-9a-f]{32}$"),
]


@router.get("/placeholders/narration/{language}/{token}.wav")
def get_placeholder_narration(
    language: StoryLanguage,
    token: NarrationToken,
) -> Response:
    return Response(
        content=generate_placeholder_wav(token),
        media_type="audio/wav",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


@router.get("/narration/{token}.mp3")
def get_generated_narration(token: GeneratedNarrationToken) -> Response:
    try:
        content = read_narration_mp3(token)
    except FileNotFoundError:
        raise HTTPException(status_code=404) from None
    return Response(
        content=content,
        media_type="audio/mpeg",
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )

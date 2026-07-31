from typing import Annotated

from fastapi import APIRouter, Path, Response

from app.schemas import StoryLanguage
from app.services.narration import generate_placeholder_wav


router = APIRouter(prefix="/media/placeholders", tags=["media"])
NarrationToken = Annotated[str, Path(pattern=r"^[0-9a-f]{16}$")]


@router.get("/narration/{language}/{token}.wav")
def get_placeholder_narration(
    language: StoryLanguage,
    token: NarrationToken,
) -> Response:
    return Response(
        content=generate_placeholder_wav(token),
        media_type="audio/wav",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.models import Parent
from app.schemas import Locale, ParentOut


class StoryForgeTestClient(TestClient):
    """Test client with private database-backed fixture factories."""

    db_session_factory: sessionmaker[Session]

    def create_parent(
        self,
        email: str = "parent@example.com",
        locale: Locale = "en",
    ) -> dict[str, object]:
        with self.db_session_factory() as session:
            parent = Parent(
                email=email.lower(),
                locale=locale,
                hashed_password="unused-in-tests",
            )
            session.add(parent)
            session.commit()
            session.refresh(parent)
            return ParentOut.model_validate(parent).model_dump(mode="json")

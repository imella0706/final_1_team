import pytest

from app.extensions.ad_content.main import app as extension_app
from app.main import app as main_app
from app.modules.auth.dependencies import get_current_user


@pytest.fixture(autouse=True)
def authenticate_legacy_endpoint_tests():
    # [Design Intent] Existing model tests isolate their original behavior. Auth's
    # actual database and token boundary is covered in dedicated integration tests.
    main_app.dependency_overrides[get_current_user] = lambda: None
    extension_app.dependency_overrides[get_current_user] = lambda: None
    yield
    main_app.dependency_overrides.pop(get_current_user, None)
    extension_app.dependency_overrides.pop(get_current_user, None)

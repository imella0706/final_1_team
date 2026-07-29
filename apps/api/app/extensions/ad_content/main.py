from app.core.config import settings
from app.main import create_app

# [Design Intent] The historical entrypoint delegates to the canonical factory so
# CORS, authentication, errors, and shutdown behavior cannot drift between apps.
app = create_app(
    title=f"{settings.app_name} Ad Content Extension",
    include_legacy_runtime_routes=True,
)

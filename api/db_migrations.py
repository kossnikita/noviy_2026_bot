import logging
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig

logger = logging.getLogger("migrations")


def upgrade_head() -> None:
    """Run `alembic upgrade head` using api/alembic.ini."""
    api_dir = Path(__file__).resolve().parent
    root = api_dir.parent
    ini_path = api_dir / "alembic.ini"
    if not ini_path.exists():
        raise RuntimeError(f"alembic.ini not found at {ini_path}")

    alembic_cfg = AlembicConfig(str(ini_path))
    # Ensure `import api.*` works regardless of CWD.
    alembic_cfg.set_main_option("prepend_sys_path", str(root))
    alembic_cfg.set_main_option("script_location", str(api_dir / "alembic"))

    logger.info("Running alembic upgrade head")
    command.upgrade(alembic_cfg, "head")
    logger.info("Alembic upgrade complete")

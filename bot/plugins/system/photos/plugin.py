import logging
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from bot.api_repos import ApiSettings, PhotosRepo, _Api, _api_base_url_from_env


_LOG = logging.getLogger("photos")


def _repo_root() -> Path:
    # bot/plugins/system/photos/plugin.py -> repo root
    return Path(__file__).resolve().parents[4]


def _img_dir() -> Path:
    return _repo_root() / "data" / "img"


def _public_url(filename: str) -> str:
    # Reverse proxy is expected to serve repo_root/data/img at /img.
    return f"/img/{filename}"


class Plugin:
    name = "photos"

    def register_user(self, router: Router) -> None:
        _LOG.info("photos plugin: register_user called for router=%s", getattr(router, "name", None))
        # This plugin is intended for group chats; actual registration is in register_group.

    def register_group(self, router: Router) -> None:
        _LOG.info("photos plugin: register_group called for router=%s", getattr(router, "name", None))
        router.message.register(self._on_group_photo, F.photo)

    def register_admin(self, router: Router) -> None:
        return

    def user_menu_button(self):
        return None

    def admin_menu_button(self):
        return None

    async def _on_group_photo(self, message: Message, bot: Bot) -> None:
        _LOG.info(
            "photos plugin: handler entered chat_id=%s type=%s msg_id=%s user_id=%s photo_count=%s",
            getattr(message.chat, "id", None),
            getattr(message.chat, "type", None),
            getattr(message, "message_id", None),
            getattr(getattr(message, "from_user", None), "id", None),
            len(message.photo or []),
        )
        chat = message.chat
        if chat is None or chat.type not in {ChatType.GROUP, ChatType.SUPERGROUP}:
            _LOG.info("photos plugin: skipping non-group chat: %s", getattr(chat, "type", None))
            return

        if not message.photo:
            return

        user = message.from_user
        if user is None:
            return

        best = message.photo[-1]
        try:
            file = await bot.get_file(best.file_id)
        except Exception:
            _LOG.exception("Failed to get file for photo")
            return

        _LOG.info(
            "photos plugin: got file_id=%s file_unique_id=%s file_path=%s",
            best.file_id,
            getattr(best, "file_unique_id", None),
            getattr(file, "file_path", None),
        )

        suffix = ".jpg"
        try:
            fp = str(getattr(file, "file_path", "") or "")
            if "." in fp:
                suffix = "." + fp.rsplit(".", 1)[-1]
                if len(suffix) > 8:
                    suffix = ".jpg"
        except Exception:
            suffix = ".jpg"

        filename = f"{int(chat.id)}_{int(message.message_id)}_{best.file_unique_id}{suffix}"
        dst_dir = _img_dir()
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst_path = dst_dir / filename

        try:
            if not dst_path.exists():
                assert file.file_path is not None
                await bot.download_file(file.file_path, destination=dst_path)
                _LOG.info("Downloaded photo to %s", dst_path)
            else:
                _LOG.info("Photo already exists at %s", dst_path)
        except Exception:
            _LOG.exception("Failed to download photo to %s", dst_path)
            return

        # Record in API DB
        try:
            api = _Api(ApiSettings(base_url=_api_base_url_from_env(), timeout_s=5.0))
            photos = PhotosRepo(api)
            photos.create(
                name=filename,
                url=_public_url(filename),
                added_by=int(user.id),
            )
            _LOG.info("photos plugin: recorded photo in API name=%s", filename)
        except Exception:
            _LOG.exception("Failed to record photo in API")
            # Keep the file even if DB insert fails.
            return

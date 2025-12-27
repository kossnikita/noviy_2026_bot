import logging
from pathlib import Path
import os
from collections import OrderedDict

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.types import Message

from bot.api_repos import ApiSettings, PhotosRepo, _Api
from bot.config import load_config


_LOG = logging.getLogger("photos")

_PROCESSED_UNIQUE_IDS: "OrderedDict[str, None]" = OrderedDict()
_INFLIGHT_UNIQUE_IDS: set[str] = set()
_MAX_PROCESSED_UNIQUE_IDS = 5000


def _seen_unique_id(uid: str) -> bool:
    if not uid:
        return False
    if uid in _INFLIGHT_UNIQUE_IDS:
        return True
    return uid in _PROCESSED_UNIQUE_IDS


def _mark_inflight(uid: str) -> None:
    if uid:
        _INFLIGHT_UNIQUE_IDS.add(uid)


def _unmark_inflight(uid: str) -> None:
    if uid:
        _INFLIGHT_UNIQUE_IDS.discard(uid)


def _mark_processed(uid: str) -> None:
    if not uid:
        return
    _PROCESSED_UNIQUE_IDS[uid] = None
    _PROCESSED_UNIQUE_IDS.move_to_end(uid)
    while len(_PROCESSED_UNIQUE_IDS) > _MAX_PROCESSED_UNIQUE_IDS:
        _PROCESSED_UNIQUE_IDS.popitem(last=False)


def _repo_root() -> Path:
    # bot/plugins/system/photos/plugin.py -> repo root
    return Path(__file__).resolve().parents[4]


def _img_dir() -> Path:
    return _repo_root() / "data" / "img"


def _public_url(filename: str) -> str:
    # Reverse proxy is expected to serve repo_root/data/img at /img.
    return f"/img/{filename}"


def _tmp_dir() -> Path:
    # In containers /tmp is always available. Keep it overrideable for tests.
    return Path(os.environ.get("BOT_TMP_DIR", "/tmp"))


class Plugin:
    name = "photos"

    def register_user(self, router: Router) -> None:
        _LOG.info(
            "photos plugin: register_user called for router=%s",
            getattr(router, "name", None),
        )
        # This plugin is intended for group chats; actual registration is in register_group.

    def register_group(self, router: Router) -> None:
        _LOG.info(
            "photos plugin: register_group called for router=%s",
            getattr(router, "name", None),
        )
        router.message.register(self._on_group_photo, F.photo)

    def register_admin(self, router: Router) -> None:
        return

    def user_menu_button(self):
        return None

    def admin_menu_button(self):
        return None

    async def _on_group_photo(self, message: Message, bot: Bot) -> None:
        _LOG.info(
            (
                "photos plugin: handler entered chat_id=%s type=%s "
                "msg_id=%s user_id=%s photo_count=%s"
            ),
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

        unique_id = str(getattr(best, "file_unique_id", "") or "").strip()
        if unique_id and _seen_unique_id(unique_id):
            _LOG.info("photos plugin: duplicate file_unique_id=%s; skipping", unique_id)
            return
        _mark_inflight(unique_id)
        try:
            file = await bot.get_file(best.file_id)
        except Exception:
            _unmark_inflight(unique_id)
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

        # Telegram's file_unique_id is stable for the same file contents.
        # Use it as the storage key to avoid duplicates across messages.
        base = unique_id or f"{int(chat.id)}_{int(message.message_id)}"
        filename = f"{base}{suffix}"
        dst_dir = _tmp_dir()
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst_path = dst_dir / filename

        try:
            try:
                assert file.file_path is not None
                await bot.download_file(file.file_path, destination=dst_path)
                _LOG.info("Downloaded photo to %s", dst_path)
            except Exception:
                _LOG.exception("Failed to download photo to %s", dst_path)
                return

            # Upload to API (API stores in its own volume) and record in DB.
            cfg = load_config()
            api = _Api(
                ApiSettings(
                    base_url=cfg.api_base_url,
                    timeout_s=15.0,
                    token=cfg.api_token,
                )
            )
            photos = PhotosRepo(api)
            photos.upload(
                file_path=str(dst_path),
                filename=filename,
                added_by=int(user.id),
            )
            _LOG.info("photos plugin: uploaded photo to API name=%s", filename)
            _mark_processed(unique_id)
        except Exception:
            _LOG.exception("Failed to upload photo to API")
        finally:
            _unmark_inflight(unique_id)
            try:
                if dst_path.exists():
                    dst_path.unlink()
                    _LOG.info("Removed temp photo %s", dst_path)
            except Exception:
                _LOG.exception("Failed to remove temp photo %s", dst_path)

from typing import Protocol, Tuple, Optional
from aiogram import Router


class ContestPlugin(Protocol):
    name: str
    slug: str  # unique prefix for callback/data routing

    def register_user(self, router: Router) -> None: ...
    def register_admin(self, router: Router) -> None: ...

    def user_menu_button(self) -> Tuple[str, str]:
        """Return (text, callback_data). callback_data should begin with slug+":"""
        ...

    def admin_menu_button(self) -> Optional[Tuple[str, str]]:
        """Return (text, callback_data) or None to skip from admin menu."""
        ...


class SystemPlugin(Protocol):
    """Non-contest plugin.

    Used for bot features that should not appear in the contest menus.
    """

    name: str

    def register_user(self, router: Router) -> None: ...
    def register_admin(self, router: Router) -> None: ...

    def user_menu_button(self) -> Optional[Tuple[str, str]]:
        """Return (text, callback_data) or None to skip from user menu."""
        ...

    def admin_menu_button(self) -> Optional[Tuple[str, str]]:
        """Return (text, callback_data) or None to skip from admin menu."""
        ...

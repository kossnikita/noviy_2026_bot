import importlib
import pkgutil
import logging
from typing import List

from aiogram import Router

from .interfaces import ContestPlugin


class PluginRegistry:
    def __init__(self):
        self.plugins: List[ContestPlugin] = []
        self._log = logging.getLogger(self.__class__.__name__)

    def load_contest_plugins(self) -> None:
        base_pkg = 'bot.plugins.contests'
        try:
            pkg = importlib.import_module(base_pkg)
        except ModuleNotFoundError:
            self._log.info("No contests package found: %s", base_pkg)
            return

        for finder, name, ispkg in pkgutil.iter_modules(pkg.__path__, prefix=f"{base_pkg}."):
            # Expect a module with submodule 'plugin' exporting 'Plugin'
            plugin_module_name = f"{name}.plugin"
            try:
                mod = importlib.import_module(plugin_module_name)
            except ModuleNotFoundError:
                self._log.warning("Contest plugin module not found: %s", plugin_module_name)
                continue
            if not hasattr(mod, 'Plugin'):
                self._log.warning("Plugin class not found in module: %s", plugin_module_name)
                continue
            plugin = getattr(mod, 'Plugin')
            instance: ContestPlugin = plugin()
            self.plugins.append(instance)
            self._log.info(
                "Loaded contest plugin: %s (%s)",
                getattr(instance, 'name', 'unknown'),
                getattr(instance, 'slug', 'n/a'),
            )

    def register_all(self, user_router: Router, admin_router: Router) -> None:
        for p in self.plugins:
            p.register_user(user_router)
            p.register_admin(admin_router)

    def user_menu_entries(self):
        for p in self.plugins:
            yield p.user_menu_button()

    def admin_menu_entries(self):
        for p in self.plugins:
            btn = p.admin_menu_button()
            if btn:
                yield btn


registry = PluginRegistry()

import importlib
import pkgutil
import logging
import asyncio
from typing import List

from aiogram import Bot, Router

from .interfaces import ContestPlugin, SystemPlugin


class PluginRegistry:
    def __init__(self):
        self.plugins: List[ContestPlugin] = []
        self.system_plugins: List[SystemPlugin] = []
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

    def load_system_plugins(self) -> None:
        base_pkg = 'bot.plugins.system'
        try:
            pkg = importlib.import_module(base_pkg)
        except ModuleNotFoundError:
            self._log.info("No system plugins package found: %s", base_pkg)
            return

        for finder, name, ispkg in pkgutil.iter_modules(pkg.__path__, prefix=f"{base_pkg}."):
            plugin_module_name = f"{name}.plugin"
            try:
                mod = importlib.import_module(plugin_module_name)
            except ModuleNotFoundError:
                self._log.warning("System plugin module not found: %s", plugin_module_name)
                continue
            if not hasattr(mod, 'Plugin'):
                self._log.warning("Plugin class not found in module: %s", plugin_module_name)
                continue
            plugin = getattr(mod, 'Plugin')
            instance: SystemPlugin = plugin()
            self.system_plugins.append(instance)
            self._log.info(
                "Loaded system plugin: %s",
                getattr(instance, 'name', 'unknown'),
            )

    def load_all_plugins(self) -> None:
        self.load_contest_plugins()
        self.load_system_plugins()

    def register_all(
        self,
        user_router: Router,
        admin_router: Router,
        group_router: Router | None = None,
    ) -> None:
        for p in self.plugins:
            p.register_user(user_router)
            p.register_admin(admin_router)

        for p in self.system_plugins:
            p.register_user(user_router)
            p.register_admin(admin_router)

            if group_router is not None:
                reg_group = getattr(p, "register_group", None)
                if callable(reg_group):
                    try:
                        reg_group(group_router)
                        self._log.info(
                            "Registered system plugin into group router: %s",
                            getattr(p, "name", "unknown"),
                        )
                    except Exception:
                        self._log.exception(
                            "Failed to register system plugin into group router: %s",
                            getattr(p, "name", "unknown"),
                        )

    def start_system_background_tasks(self, bot: Bot) -> list[asyncio.Task[None]]:
        tasks: list[asyncio.Task[None]] = []
        for p in self.system_plugins:
            start = getattr(p, "start", None)
            if callable(start):
                try:
                    t = start(bot)
                except Exception:
                    continue
                if isinstance(t, asyncio.Task):
                    tasks.append(t)
        return tasks

    def user_menu_entries(self):
        for p in self.plugins:
            yield p.user_menu_button()

        for p in self.system_plugins:
            btn = getattr(p, "user_menu_button", None)
            if callable(btn):
                v = btn()
                if v:
                    yield v

    def admin_menu_entries(self):
        for p in self.plugins:
            btn = p.admin_menu_button()
            if btn:
                yield btn

        for p in self.system_plugins:
            btn = getattr(p, "admin_menu_button", None)
            if callable(btn):
                v = btn()
                if v:
                    yield v


registry = PluginRegistry()

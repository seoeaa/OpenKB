"""Plugin system for OpenKB.

Plugins are Python modules or packages placed in `.openkb/plugins/`.
Each plugin can register:
- Slash commands for the chat REPL
- Hooks (pre/post compile, pre/post query)
- MCP tools and resources
- CLI commands (via Click groups)

A plugin is a directory containing __init__.py with a `setup()` function,
or a single .py file with a `setup()` function at module level.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

# Hooks that plugins can register
_hooks: dict[str, list[Callable]] = {
    "pre_compile": [],
    "post_compile": [],
    "pre_query": [],
    "post_query": [],
    "pre_lint": [],
    "post_lint": [],
    "on_startup": [],
}

_plugin_modules: list[ModuleType] = []


def register_hook(hook_name: str, callback: Callable) -> None:
    """Register a lifecycle hook callback."""
    if hook_name not in _hooks:
        _hooks[hook_name] = []
    _hooks[hook_name].append(callback)


def run_hooks(hook_name: str, **kwargs) -> list[Any]:
    """Run all registered hooks for a given lifecycle event."""
    results = []
    for callback in _hooks.get(hook_name, []):
        try:
            result = callback(**kwargs)
            results.append(result)
        except Exception as exc:
            import logging
            logging.getLogger("openkb.plugins").warning(
                "Hook %s in plugin failed: %s", hook_name, exc
            )
    return results


def get_custom_slash_commands() -> list[dict]:
    """Return slash commands registered by plugins.

    Returns list of dicts with keys: name, description, handler, needs_arg, arg_help.
    """
    commands = []
    for mod in _plugin_modules:
        if hasattr(mod, "get_slash_commands"):
            try:
                cmds = mod.get_slash_commands()
                if cmds:
                    commands.extend(cmds)
            except Exception:
                pass
    return commands


def discover_plugins(kb_dir: Path) -> int:
    """Load all plugins from the KB's plugins directory.

    Args:
        kb_dir: Knowledge base root directory.

    Returns:
        Number of plugins loaded.
    """
    global _plugin_modules
    plugins_dir = kb_dir / ".openkb" / "plugins"
    if not plugins_dir.exists():
        plugins_dir.mkdir(parents=True, exist_ok=True)
        return 0

    loaded = 0

    for entry in sorted(plugins_dir.iterdir()):
        if entry.name.startswith("_") or entry.name.startswith("."):
            continue

        module_name = f"openkb_plugin_{entry.stem}"

        try:
            if entry.is_dir() and (entry / "__init__.py").exists():
                spec = importlib.util.spec_from_file_location(
                    module_name, str(entry / "__init__.py")
                )
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    _setup_plugin(mod)
                    _plugin_modules.append(mod)
                    loaded += 1
            elif entry.suffix == ".py" and entry.is_file():
                spec = importlib.util.spec_from_file_location(
                    module_name, str(entry)
                )
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    _setup_plugin(mod)
                    _plugin_modules.append(mod)
                    loaded += 1
        except Exception as exc:
            import logging
            logging.getLogger("openkb.plugins").warning(
                "Failed to load plugin %s: %s", entry.name, exc
            )

    return loaded


def _setup_plugin(mod: ModuleType) -> None:
    """Call the plugin's setup() function if it exists."""
    if hasattr(mod, "setup"):
        try:
            mod.setup(register_hook)
        except Exception:
            pass


def get_plugin_count() -> int:
    return len(_plugin_modules)

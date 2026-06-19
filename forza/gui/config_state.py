from __future__ import annotations

from dataclasses import dataclass, fields, is_dataclass
from typing import Iterable

from PySide6.QtCore import QObject, Signal

from ..config import AppConfig, load_config
from ..application import ConfigFileService, ConfigSaveResult


_PATH_FIELDS = {
    "input_dir",
    "pdf_file",
    "log_file",
    "database_file",
}
_TOP_LEVEL_FIELD_KEYS = {
    "gamertag": "user.gamertag",
    "workers": "llm.workers",
}


@dataclass(frozen=True)
class ConfigChangeSet:
    """Field-level summary for a GUI config update.

    Keys follow the same dotted notation used by Settings writes, for example
    ``llm.workers`` or ``paths.database_file``. The ``all`` flag is used for
    initial wiring and full reloads where consumers should treat every derived
    value as potentially changed.
    """

    changed: frozenset[str]
    all: bool = False

    @classmethod
    def initial(cls) -> "ConfigChangeSet":
        return cls(frozenset(), all=True)

    @classmethod
    def from_configs(cls, old: AppConfig, new: AppConfig) -> "ConfigChangeSet":
        old_values = dict(_iter_config_values(old))
        new_values = dict(_iter_config_values(new))
        if old_values.keys() != new_values.keys():
            old_only = sorted(old_values.keys() - new_values.keys())
            new_only = sorted(new_values.keys() - old_values.keys())
            raise ValueError(
                "Config diff key mismatch: "
                f"old_only={old_only!r}; new_only={new_only!r}"
            )
        changed = {
            key
            for key, old_value in old_values.items()
            if old_value != new_values[key]
        }
        return cls(frozenset(changed))

    def affects(self, *keys_or_prefixes: str) -> bool:
        if self.all:
            return True
        for requested in keys_or_prefixes:
            if requested in self.changed:
                return True
            prefix = requested.rstrip(".") + "."
            if any(key.startswith(prefix) for key in self.changed):
                return True
        return False

    def __bool__(self) -> bool:
        return self.all or bool(self.changed)


class GuiConfigState(QObject):
    """Single live owner of GUI configuration.

    Controllers should read ``current`` at action time. Components that keep
    derived resources, such as database readers, should subscribe to ``changed``
    and rebuild only when relevant keys change.
    """

    changed = Signal(object, object)  # AppConfig, ConfigChangeSet
    save_failed = Signal(str)

    def __init__(self, *, cfg: AppConfig, config_path: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._config_path = str(config_path)
        self._writer = ConfigFileService(self._config_path)

    @property
    def current(self) -> AppConfig:
        return self._cfg

    @property
    def config_path(self) -> str:
        return self._config_path

    def reload(self, *, strict: bool = True, emit: bool = True) -> AppConfig:
        cfg = load_config(self._config_path, strict=strict)
        if emit:
            self.set_config(cfg)
        else:
            self._cfg = cfg
        return cfg

    def save_changes(self, changes: dict[str, str]) -> ConfigSaveResult:
        result = self._writer.save_changes(changes)
        if not result.ok:
            self.save_failed.emit(result.message)
            return result
        self.reload(strict=True, emit=True)
        return result

    def validate_changes(self, changes: dict[str, str]):
        return self._writer.validate_changes(changes)

    def set_config(self, cfg: AppConfig) -> ConfigChangeSet:
        old = self._cfg
        self._cfg = cfg
        changes = ConfigChangeSet.from_configs(old, cfg)
        if changes:
            self.changed.emit(cfg, changes)
        return changes


def connect_config_aware(config_state: GuiConfigState, component: object, *, initialize: bool = True) -> None:
    """Connect a component that implements the explicit GUI config contract."""

    handler = getattr(component, "on_config_changed", None)
    if not callable(handler):
        raise TypeError(
            f"{component.__class__.__name__} must implement "
            "on_config_changed(cfg, changes) before it can be registered as config-aware"
        )
    config_state.changed.connect(handler)
    if initialize:
        handler(config_state.current, ConfigChangeSet.initial())


def connect_many_config_aware(config_state: GuiConfigState, components: Iterable[object]) -> None:
    for component in components:
        connect_config_aware(config_state, component)


def _iter_config_values(cfg: AppConfig) -> Iterable[tuple[str, object]]:
    """Yield stable config-change keys and values for every AppConfig field.

    Top-level AppConfig fields are grouped by the INI section vocabulary used by
    Settings. Nested dataclasses are expanded recursively so adding a field to
    LLMConfig/ImageConfig/ValidationConfig/PDFConfig/PromptConfig is picked up
    automatically by the GUI change detector.
    """

    if not is_dataclass(cfg):
        raise TypeError(f"Expected dataclass AppConfig, got {type(cfg)!r}")
    for field in fields(cfg):
        value = getattr(cfg, field.name)
        if field.name in _PATH_FIELDS:
            yield f"paths.{field.name}", value
            continue
        mapped_key = _TOP_LEVEL_FIELD_KEYS.get(field.name)
        if mapped_key is not None:
            yield mapped_key, value
            continue
        if is_dataclass(value):
            yield from _iter_nested_config_values(field.name, value)
            continue
        raise ValueError(
            f"AppConfig field {field.name!r} has no GUI config diff key mapping"
        )


def _iter_nested_config_values(prefix: str, value: object) -> Iterable[tuple[str, object]]:
    if not is_dataclass(value):
        raise TypeError(f"Expected dataclass value for {prefix!r}, got {type(value)!r}")
    for field in fields(value):
        nested_value = getattr(value, field.name)
        if is_dataclass(nested_value):
            yield from _iter_nested_config_values(f"{prefix}.{field.name}", nested_value)
        else:
            yield f"{prefix}.{field.name}", nested_value

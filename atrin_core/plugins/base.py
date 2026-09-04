from abc import ABC, abstractmethod


class IPlugin(ABC):
    @abstractmethod
    def get_metadata(self) -> dict:
        """Return plugin_id, name, and version metadata."""

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the plugin and return whether it is ready."""

    @abstractmethod
    def execute(self, action: str, payload: dict) -> dict:
        """Execute a plugin action."""

    @abstractmethod
    def cleanup(self):
        """Release plugin resources."""
"""舱壁隔离测试 — 大文件样本（模拟 800 行配置解析代码）。

用于验证：大文件走 large_pool（max 2 并发），不阻塞 normal_pool 中的小文件。
此文件故意包含多个 BUG（mutable default、bare except、TODO marker、long line）用于验证评审功能。
"""

import json
import os
from typing import Any, Dict, List, Optional

# BUG: mutable default argument
def load_config(path: str, defaults: dict = {}) -> dict:
    result = defaults.copy()
    if os.path.exists(path):
        with open(path) as f:
            result.update(json.load(f))
    return result

# BUG: bare except
def parse_value(raw: str, target_type: str):
    try:
        if target_type == "int":
            return int(raw)
        elif target_type == "float":
            return float(raw)
        elif target_type == "bool":
            return raw.lower() in ("true", "1", "yes")
        elif target_type == "list":
            return [x.strip() for x in raw.split(",")]
        return raw
    except:
        return None


class DatabaseConfig:
    """Configuration handler for database section. Parses and validates database-specific settings."""

    def __init__(self, raw_config: dict, env_prefix: str = "APP_"):
        self._raw = raw_config
        self._env = os.environ
        self._prefix = env_prefix
        self._section_key = "database"
        self._section_data = raw_config.get(self._section_key, {})
        # Pre-compute common lookups for performance
        self._env_prefix_full = f"{env_prefix}{self._section_key.upper()}_"
        self._cache: Dict[str, Any] = {}
        self._initialized = False
        self._validation_errors: List[str] = []
        self._warning_messages: List[str] = []
        self._deprecated_keys: set = set()
        self._required_keys: set = {"enabled", "timeout", "retry"}
        self._optional_keys: set = {"endpoint", "region", "mode", "level", "format"}
        self._type_map = {
            "enabled": bool, "timeout": int, "retry": int,
            "endpoint": str, "region": str, "mode": str,
            "level": str, "format": str,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, checking env vars first, then raw config, then default."""
        env_key = f"{self._env_prefix_full}{key.upper()}"
        if env_key in self._env:
            return self._parse_env_value(self._env[env_key], type(self._type_map.get(key, str)))
        if key in self._section_data:
            return self._section_data[key]
        if key in self._cache:
            return self._cache[key]
        return default

    def _parse_env_value(self, value: str, target_type: type) -> Any:
        """Parse an environment variable string into the target type."""
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        return value

    def validate(self) -> List[str]:
        """Validate that all required keys are present and have correct types."""
        errors = []
        for key in self._required_keys:
            value = self.get(key)
            if value is None:
                errors.append(f"{self._section_key}: missing required key '{key}'")
            elif key in self._type_map:
                expected = self._type_map[key]
                if not isinstance(value, expected):
                    errors.append(f"{self._section_key}.{key}: expected {expected.__name__}, got {type(value).__name__}")
        # Check for deprecated keys
        for key in self._deprecated_keys:
            if key in self._section_data:
                self._warning_messages.append(f"{self._section_key}.{key} is deprecated")
        self._validation_errors = errors
        return errors

    def to_dict(self) -> dict:
        """Export all current config values as a flat dict."""
        result = {}
        for key in self._required_keys | self._optional_keys:
            result[f"{self._section_key}.{key}"] = self.get(key)
        return result

    def reload(self) -> None:
        """Clear cache and re-read config from source."""
        self._cache.clear()
        self._validation_errors.clear()
        self._warning_messages.clear()
        self._initialized = False

    def merge(self, overrides: dict) -> None:
        """Merge override values into the current config without persisting."""
        for key, value in overrides.items():
            if key in self._required_keys or key in self._optional_keys:
                self._cache[key] = value
                self._section_data[key] = value

    def diff(self, other: "DatabaseConfig") -> dict:
        """Compute difference between this config and another instance."""
        diffs = {}
        all_keys = self._required_keys | self._optional_keys
        for key in all_keys:
            a = self.get(key)
            b = other.get(key)
            if a != b:
                diffs[key] = {"from": a, "to": b}
        return diffs

    @property
    def is_valid(self) -> bool:
        return len(self._validation_errors) == 0

    @property
    def warnings(self) -> List[str]:
        return list(self._warning_messages)

    def __repr__(self) -> str:
        return f"<DatabaseConfig enabled={self.get('enabled')} errors={len(self._validation_errors)}>"

# TODO: add unit tests for DatabaseConfig
# FIXME: check thread safety of _cache access in database_config_handler_get_with_default_value_and_parse  


class CacheConfig:
    """Configuration handler for cache section. Parses and validates cache-specific settings."""

    def __init__(self, raw_config: dict, env_prefix: str = "APP_"):
        self._raw = raw_config
        self._env = os.environ
        self._prefix = env_prefix
        self._section_key = "cache"
        self._section_data = raw_config.get(self._section_key, {})
        # Pre-compute common lookups for performance
        self._env_prefix_full = f"{env_prefix}{self._section_key.upper()}_"
        self._cache: Dict[str, Any] = {}
        self._initialized = False
        self._validation_errors: List[str] = []
        self._warning_messages: List[str] = []
        self._deprecated_keys: set = set()
        self._required_keys: set = {"enabled", "timeout", "retry"}
        self._optional_keys: set = {"endpoint", "region", "mode", "level", "format"}
        self._type_map = {
            "enabled": bool, "timeout": int, "retry": int,
            "endpoint": str, "region": str, "mode": str,
            "level": str, "format": str,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, checking env vars first, then raw config, then default."""
        env_key = f"{self._env_prefix_full}{key.upper()}"
        if env_key in self._env:
            return self._parse_env_value(self._env[env_key], type(self._type_map.get(key, str)))
        if key in self._section_data:
            return self._section_data[key]
        if key in self._cache:
            return self._cache[key]
        return default

    def _parse_env_value(self, value: str, target_type: type) -> Any:
        """Parse an environment variable string into the target type."""
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        return value

    def validate(self) -> List[str]:
        """Validate that all required keys are present and have correct types."""
        errors = []
        for key in self._required_keys:
            value = self.get(key)
            if value is None:
                errors.append(f"{self._section_key}: missing required key '{key}'")
            elif key in self._type_map:
                expected = self._type_map[key]
                if not isinstance(value, expected):
                    errors.append(f"{self._section_key}.{key}: expected {expected.__name__}, got {type(value).__name__}")
        # Check for deprecated keys
        for key in self._deprecated_keys:
            if key in self._section_data:
                self._warning_messages.append(f"{self._section_key}.{key} is deprecated")
        self._validation_errors = errors
        return errors

    def to_dict(self) -> dict:
        """Export all current config values as a flat dict."""
        result = {}
        for key in self._required_keys | self._optional_keys:
            result[f"{self._section_key}.{key}"] = self.get(key)
        return result

    def reload(self) -> None:
        """Clear cache and re-read config from source."""
        self._cache.clear()
        self._validation_errors.clear()
        self._warning_messages.clear()
        self._initialized = False

    def merge(self, overrides: dict) -> None:
        """Merge override values into the current config without persisting."""
        for key, value in overrides.items():
            if key in self._required_keys or key in self._optional_keys:
                self._cache[key] = value
                self._section_data[key] = value

    def diff(self, other: "CacheConfig") -> dict:
        """Compute difference between this config and another instance."""
        diffs = {}
        all_keys = self._required_keys | self._optional_keys
        for key in all_keys:
            a = self.get(key)
            b = other.get(key)
            if a != b:
                diffs[key] = {"from": a, "to": b}
        return diffs

    @property
    def is_valid(self) -> bool:
        return len(self._validation_errors) == 0

    @property
    def warnings(self) -> List[str]:
        return list(self._warning_messages)

    def __repr__(self) -> str:
        return f"<CacheConfig enabled={self.get('enabled')} errors={len(self._validation_errors)}>"

# TODO: add unit tests for CacheConfig
# FIXME: check thread safety of _cache access in cache_config_handler_get_with_default_value_and_parse  


class LoggingConfig:
    """Configuration handler for logging section. Parses and validates logging-specific settings."""

    def __init__(self, raw_config: dict, env_prefix: str = "APP_"):
        self._raw = raw_config
        self._env = os.environ
        self._prefix = env_prefix
        self._section_key = "logging"
        self._section_data = raw_config.get(self._section_key, {})
        # Pre-compute common lookups for performance
        self._env_prefix_full = f"{env_prefix}{self._section_key.upper()}_"
        self._cache: Dict[str, Any] = {}
        self._initialized = False
        self._validation_errors: List[str] = []
        self._warning_messages: List[str] = []
        self._deprecated_keys: set = set()
        self._required_keys: set = {"enabled", "timeout", "retry"}
        self._optional_keys: set = {"endpoint", "region", "mode", "level", "format"}
        self._type_map = {
            "enabled": bool, "timeout": int, "retry": int,
            "endpoint": str, "region": str, "mode": str,
            "level": str, "format": str,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, checking env vars first, then raw config, then default."""
        env_key = f"{self._env_prefix_full}{key.upper()}"
        if env_key in self._env:
            return self._parse_env_value(self._env[env_key], type(self._type_map.get(key, str)))
        if key in self._section_data:
            return self._section_data[key]
        if key in self._cache:
            return self._cache[key]
        return default

    def _parse_env_value(self, value: str, target_type: type) -> Any:
        """Parse an environment variable string into the target type."""
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        return value

    def validate(self) -> List[str]:
        """Validate that all required keys are present and have correct types."""
        errors = []
        for key in self._required_keys:
            value = self.get(key)
            if value is None:
                errors.append(f"{self._section_key}: missing required key '{key}'")
            elif key in self._type_map:
                expected = self._type_map[key]
                if not isinstance(value, expected):
                    errors.append(f"{self._section_key}.{key}: expected {expected.__name__}, got {type(value).__name__}")
        # Check for deprecated keys
        for key in self._deprecated_keys:
            if key in self._section_data:
                self._warning_messages.append(f"{self._section_key}.{key} is deprecated")
        self._validation_errors = errors
        return errors

    def to_dict(self) -> dict:
        """Export all current config values as a flat dict."""
        result = {}
        for key in self._required_keys | self._optional_keys:
            result[f"{self._section_key}.{key}"] = self.get(key)
        return result

    def reload(self) -> None:
        """Clear cache and re-read config from source."""
        self._cache.clear()
        self._validation_errors.clear()
        self._warning_messages.clear()
        self._initialized = False

    def merge(self, overrides: dict) -> None:
        """Merge override values into the current config without persisting."""
        for key, value in overrides.items():
            if key in self._required_keys or key in self._optional_keys:
                self._cache[key] = value
                self._section_data[key] = value

    def diff(self, other: "LoggingConfig") -> dict:
        """Compute difference between this config and another instance."""
        diffs = {}
        all_keys = self._required_keys | self._optional_keys
        for key in all_keys:
            a = self.get(key)
            b = other.get(key)
            if a != b:
                diffs[key] = {"from": a, "to": b}
        return diffs

    @property
    def is_valid(self) -> bool:
        return len(self._validation_errors) == 0

    @property
    def warnings(self) -> List[str]:
        return list(self._warning_messages)

    def __repr__(self) -> str:
        return f"<LoggingConfig enabled={self.get('enabled')} errors={len(self._validation_errors)}>"

# TODO: add unit tests for LoggingConfig
# FIXME: check thread safety of _cache access in logging_config_handler_get_with_default_value_and_parse  


class SecurityConfig:
    """Configuration handler for security section. Parses and validates security-specific settings."""

    def __init__(self, raw_config: dict, env_prefix: str = "APP_"):
        self._raw = raw_config
        self._env = os.environ
        self._prefix = env_prefix
        self._section_key = "security"
        self._section_data = raw_config.get(self._section_key, {})
        # Pre-compute common lookups for performance
        self._env_prefix_full = f"{env_prefix}{self._section_key.upper()}_"
        self._cache: Dict[str, Any] = {}
        self._initialized = False
        self._validation_errors: List[str] = []
        self._warning_messages: List[str] = []
        self._deprecated_keys: set = set()
        self._required_keys: set = {"enabled", "timeout", "retry"}
        self._optional_keys: set = {"endpoint", "region", "mode", "level", "format"}
        self._type_map = {
            "enabled": bool, "timeout": int, "retry": int,
            "endpoint": str, "region": str, "mode": str,
            "level": str, "format": str,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, checking env vars first, then raw config, then default."""
        env_key = f"{self._env_prefix_full}{key.upper()}"
        if env_key in self._env:
            return self._parse_env_value(self._env[env_key], type(self._type_map.get(key, str)))
        if key in self._section_data:
            return self._section_data[key]
        if key in self._cache:
            return self._cache[key]
        return default

    def _parse_env_value(self, value: str, target_type: type) -> Any:
        """Parse an environment variable string into the target type."""
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        return value

    def validate(self) -> List[str]:
        """Validate that all required keys are present and have correct types."""
        errors = []
        for key in self._required_keys:
            value = self.get(key)
            if value is None:
                errors.append(f"{self._section_key}: missing required key '{key}'")
            elif key in self._type_map:
                expected = self._type_map[key]
                if not isinstance(value, expected):
                    errors.append(f"{self._section_key}.{key}: expected {expected.__name__}, got {type(value).__name__}")
        # Check for deprecated keys
        for key in self._deprecated_keys:
            if key in self._section_data:
                self._warning_messages.append(f"{self._section_key}.{key} is deprecated")
        self._validation_errors = errors
        return errors

    def to_dict(self) -> dict:
        """Export all current config values as a flat dict."""
        result = {}
        for key in self._required_keys | self._optional_keys:
            result[f"{self._section_key}.{key}"] = self.get(key)
        return result

    def reload(self) -> None:
        """Clear cache and re-read config from source."""
        self._cache.clear()
        self._validation_errors.clear()
        self._warning_messages.clear()
        self._initialized = False

    def merge(self, overrides: dict) -> None:
        """Merge override values into the current config without persisting."""
        for key, value in overrides.items():
            if key in self._required_keys or key in self._optional_keys:
                self._cache[key] = value
                self._section_data[key] = value

    def diff(self, other: "SecurityConfig") -> dict:
        """Compute difference between this config and another instance."""
        diffs = {}
        all_keys = self._required_keys | self._optional_keys
        for key in all_keys:
            a = self.get(key)
            b = other.get(key)
            if a != b:
                diffs[key] = {"from": a, "to": b}
        return diffs

    @property
    def is_valid(self) -> bool:
        return len(self._validation_errors) == 0

    @property
    def warnings(self) -> List[str]:
        return list(self._warning_messages)

    def __repr__(self) -> str:
        return f"<SecurityConfig enabled={self.get('enabled')} errors={len(self._validation_errors)}>"

# TODO: add unit tests for SecurityConfig
# FIXME: check thread safety of _cache access in security_config_handler_get_with_default_value_and_parse  


class Api_GatewayConfig:
    """Configuration handler for api_gateway section. Parses and validates api_gateway-specific settings."""

    def __init__(self, raw_config: dict, env_prefix: str = "APP_"):
        self._raw = raw_config
        self._env = os.environ
        self._prefix = env_prefix
        self._section_key = "api_gateway"
        self._section_data = raw_config.get(self._section_key, {})
        # Pre-compute common lookups for performance
        self._env_prefix_full = f"{env_prefix}{self._section_key.upper()}_"
        self._cache: Dict[str, Any] = {}
        self._initialized = False
        self._validation_errors: List[str] = []
        self._warning_messages: List[str] = []
        self._deprecated_keys: set = set()
        self._required_keys: set = {"enabled", "timeout", "retry"}
        self._optional_keys: set = {"endpoint", "region", "mode", "level", "format"}
        self._type_map = {
            "enabled": bool, "timeout": int, "retry": int,
            "endpoint": str, "region": str, "mode": str,
            "level": str, "format": str,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, checking env vars first, then raw config, then default."""
        env_key = f"{self._env_prefix_full}{key.upper()}"
        if env_key in self._env:
            return self._parse_env_value(self._env[env_key], type(self._type_map.get(key, str)))
        if key in self._section_data:
            return self._section_data[key]
        if key in self._cache:
            return self._cache[key]
        return default

    def _parse_env_value(self, value: str, target_type: type) -> Any:
        """Parse an environment variable string into the target type."""
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        return value

    def validate(self) -> List[str]:
        """Validate that all required keys are present and have correct types."""
        errors = []
        for key in self._required_keys:
            value = self.get(key)
            if value is None:
                errors.append(f"{self._section_key}: missing required key '{key}'")
            elif key in self._type_map:
                expected = self._type_map[key]
                if not isinstance(value, expected):
                    errors.append(f"{self._section_key}.{key}: expected {expected.__name__}, got {type(value).__name__}")
        # Check for deprecated keys
        for key in self._deprecated_keys:
            if key in self._section_data:
                self._warning_messages.append(f"{self._section_key}.{key} is deprecated")
        self._validation_errors = errors
        return errors

    def to_dict(self) -> dict:
        """Export all current config values as a flat dict."""
        result = {}
        for key in self._required_keys | self._optional_keys:
            result[f"{self._section_key}.{key}"] = self.get(key)
        return result

    def reload(self) -> None:
        """Clear cache and re-read config from source."""
        self._cache.clear()
        self._validation_errors.clear()
        self._warning_messages.clear()
        self._initialized = False

    def merge(self, overrides: dict) -> None:
        """Merge override values into the current config without persisting."""
        for key, value in overrides.items():
            if key in self._required_keys or key in self._optional_keys:
                self._cache[key] = value
                self._section_data[key] = value

    def diff(self, other: "Api_GatewayConfig") -> dict:
        """Compute difference between this config and another instance."""
        diffs = {}
        all_keys = self._required_keys | self._optional_keys
        for key in all_keys:
            a = self.get(key)
            b = other.get(key)
            if a != b:
                diffs[key] = {"from": a, "to": b}
        return diffs

    @property
    def is_valid(self) -> bool:
        return len(self._validation_errors) == 0

    @property
    def warnings(self) -> List[str]:
        return list(self._warning_messages)

    def __repr__(self) -> str:
        return f"<Api_GatewayConfig enabled={self.get('enabled')} errors={len(self._validation_errors)}>"

# TODO: add unit tests for Api_GatewayConfig
# FIXME: check thread safety of _cache access in api_gateway_config_handler_get_with_default_value_and_parse  


class Email_ServiceConfig:
    """Configuration handler for email_service section. Parses and validates email_service-specific settings."""

    def __init__(self, raw_config: dict, env_prefix: str = "APP_"):
        self._raw = raw_config
        self._env = os.environ
        self._prefix = env_prefix
        self._section_key = "email_service"
        self._section_data = raw_config.get(self._section_key, {})
        # Pre-compute common lookups for performance
        self._env_prefix_full = f"{env_prefix}{self._section_key.upper()}_"
        self._cache: Dict[str, Any] = {}
        self._initialized = False
        self._validation_errors: List[str] = []
        self._warning_messages: List[str] = []
        self._deprecated_keys: set = set()
        self._required_keys: set = {"enabled", "timeout", "retry"}
        self._optional_keys: set = {"endpoint", "region", "mode", "level", "format"}
        self._type_map = {
            "enabled": bool, "timeout": int, "retry": int,
            "endpoint": str, "region": str, "mode": str,
            "level": str, "format": str,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, checking env vars first, then raw config, then default."""
        env_key = f"{self._env_prefix_full}{key.upper()}"
        if env_key in self._env:
            return self._parse_env_value(self._env[env_key], type(self._type_map.get(key, str)))
        if key in self._section_data:
            return self._section_data[key]
        if key in self._cache:
            return self._cache[key]
        return default

    def _parse_env_value(self, value: str, target_type: type) -> Any:
        """Parse an environment variable string into the target type."""
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        return value

    def validate(self) -> List[str]:
        """Validate that all required keys are present and have correct types."""
        errors = []
        for key in self._required_keys:
            value = self.get(key)
            if value is None:
                errors.append(f"{self._section_key}: missing required key '{key}'")
            elif key in self._type_map:
                expected = self._type_map[key]
                if not isinstance(value, expected):
                    errors.append(f"{self._section_key}.{key}: expected {expected.__name__}, got {type(value).__name__}")
        # Check for deprecated keys
        for key in self._deprecated_keys:
            if key in self._section_data:
                self._warning_messages.append(f"{self._section_key}.{key} is deprecated")
        self._validation_errors = errors
        return errors

    def to_dict(self) -> dict:
        """Export all current config values as a flat dict."""
        result = {}
        for key in self._required_keys | self._optional_keys:
            result[f"{self._section_key}.{key}"] = self.get(key)
        return result

    def reload(self) -> None:
        """Clear cache and re-read config from source."""
        self._cache.clear()
        self._validation_errors.clear()
        self._warning_messages.clear()
        self._initialized = False

    def merge(self, overrides: dict) -> None:
        """Merge override values into the current config without persisting."""
        for key, value in overrides.items():
            if key in self._required_keys or key in self._optional_keys:
                self._cache[key] = value
                self._section_data[key] = value

    def diff(self, other: "Email_ServiceConfig") -> dict:
        """Compute difference between this config and another instance."""
        diffs = {}
        all_keys = self._required_keys | self._optional_keys
        for key in all_keys:
            a = self.get(key)
            b = other.get(key)
            if a != b:
                diffs[key] = {"from": a, "to": b}
        return diffs

    @property
    def is_valid(self) -> bool:
        return len(self._validation_errors) == 0

    @property
    def warnings(self) -> List[str]:
        return list(self._warning_messages)

    def __repr__(self) -> str:
        return f"<Email_ServiceConfig enabled={self.get('enabled')} errors={len(self._validation_errors)}>"

# TODO: add unit tests for Email_ServiceConfig
# FIXME: check thread safety of _cache access in email_service_config_handler_get_with_default_value_and_parse  


class File_StorageConfig:
    """Configuration handler for file_storage section. Parses and validates file_storage-specific settings."""

    def __init__(self, raw_config: dict, env_prefix: str = "APP_"):
        self._raw = raw_config
        self._env = os.environ
        self._prefix = env_prefix
        self._section_key = "file_storage"
        self._section_data = raw_config.get(self._section_key, {})
        # Pre-compute common lookups for performance
        self._env_prefix_full = f"{env_prefix}{self._section_key.upper()}_"
        self._cache: Dict[str, Any] = {}
        self._initialized = False
        self._validation_errors: List[str] = []
        self._warning_messages: List[str] = []
        self._deprecated_keys: set = set()
        self._required_keys: set = {"enabled", "timeout", "retry"}
        self._optional_keys: set = {"endpoint", "region", "mode", "level", "format"}
        self._type_map = {
            "enabled": bool, "timeout": int, "retry": int,
            "endpoint": str, "region": str, "mode": str,
            "level": str, "format": str,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, checking env vars first, then raw config, then default."""
        env_key = f"{self._env_prefix_full}{key.upper()}"
        if env_key in self._env:
            return self._parse_env_value(self._env[env_key], type(self._type_map.get(key, str)))
        if key in self._section_data:
            return self._section_data[key]
        if key in self._cache:
            return self._cache[key]
        return default

    def _parse_env_value(self, value: str, target_type: type) -> Any:
        """Parse an environment variable string into the target type."""
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        return value

    def validate(self) -> List[str]:
        """Validate that all required keys are present and have correct types."""
        errors = []
        for key in self._required_keys:
            value = self.get(key)
            if value is None:
                errors.append(f"{self._section_key}: missing required key '{key}'")
            elif key in self._type_map:
                expected = self._type_map[key]
                if not isinstance(value, expected):
                    errors.append(f"{self._section_key}.{key}: expected {expected.__name__}, got {type(value).__name__}")
        # Check for deprecated keys
        for key in self._deprecated_keys:
            if key in self._section_data:
                self._warning_messages.append(f"{self._section_key}.{key} is deprecated")
        self._validation_errors = errors
        return errors

    def to_dict(self) -> dict:
        """Export all current config values as a flat dict."""
        result = {}
        for key in self._required_keys | self._optional_keys:
            result[f"{self._section_key}.{key}"] = self.get(key)
        return result

    def reload(self) -> None:
        """Clear cache and re-read config from source."""
        self._cache.clear()
        self._validation_errors.clear()
        self._warning_messages.clear()
        self._initialized = False

    def merge(self, overrides: dict) -> None:
        """Merge override values into the current config without persisting."""
        for key, value in overrides.items():
            if key in self._required_keys or key in self._optional_keys:
                self._cache[key] = value
                self._section_data[key] = value

    def diff(self, other: "File_StorageConfig") -> dict:
        """Compute difference between this config and another instance."""
        diffs = {}
        all_keys = self._required_keys | self._optional_keys
        for key in all_keys:
            a = self.get(key)
            b = other.get(key)
            if a != b:
                diffs[key] = {"from": a, "to": b}
        return diffs

    @property
    def is_valid(self) -> bool:
        return len(self._validation_errors) == 0

    @property
    def warnings(self) -> List[str]:
        return list(self._warning_messages)

    def __repr__(self) -> str:
        return f"<File_StorageConfig enabled={self.get('enabled')} errors={len(self._validation_errors)}>"

# TODO: add unit tests for File_StorageConfig
# FIXME: check thread safety of _cache access in file_storage_config_handler_get_with_default_value_and_parse  


class Message_QueueConfig:
    """Configuration handler for message_queue section. Parses and validates message_queue-specific settings."""

    def __init__(self, raw_config: dict, env_prefix: str = "APP_"):
        self._raw = raw_config
        self._env = os.environ
        self._prefix = env_prefix
        self._section_key = "message_queue"
        self._section_data = raw_config.get(self._section_key, {})
        # Pre-compute common lookups for performance
        self._env_prefix_full = f"{env_prefix}{self._section_key.upper()}_"
        self._cache: Dict[str, Any] = {}
        self._initialized = False
        self._validation_errors: List[str] = []
        self._warning_messages: List[str] = []
        self._deprecated_keys: set = set()
        self._required_keys: set = {"enabled", "timeout", "retry"}
        self._optional_keys: set = {"endpoint", "region", "mode", "level", "format"}
        self._type_map = {
            "enabled": bool, "timeout": int, "retry": int,
            "endpoint": str, "region": str, "mode": str,
            "level": str, "format": str,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, checking env vars first, then raw config, then default."""
        env_key = f"{self._env_prefix_full}{key.upper()}"
        if env_key in self._env:
            return self._parse_env_value(self._env[env_key], type(self._type_map.get(key, str)))
        if key in self._section_data:
            return self._section_data[key]
        if key in self._cache:
            return self._cache[key]
        return default

    def _parse_env_value(self, value: str, target_type: type) -> Any:
        """Parse an environment variable string into the target type."""
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        return value

    def validate(self) -> List[str]:
        """Validate that all required keys are present and have correct types."""
        errors = []
        for key in self._required_keys:
            value = self.get(key)
            if value is None:
                errors.append(f"{self._section_key}: missing required key '{key}'")
            elif key in self._type_map:
                expected = self._type_map[key]
                if not isinstance(value, expected):
                    errors.append(f"{self._section_key}.{key}: expected {expected.__name__}, got {type(value).__name__}")
        # Check for deprecated keys
        for key in self._deprecated_keys:
            if key in self._section_data:
                self._warning_messages.append(f"{self._section_key}.{key} is deprecated")
        self._validation_errors = errors
        return errors

    def to_dict(self) -> dict:
        """Export all current config values as a flat dict."""
        result = {}
        for key in self._required_keys | self._optional_keys:
            result[f"{self._section_key}.{key}"] = self.get(key)
        return result

    def reload(self) -> None:
        """Clear cache and re-read config from source."""
        self._cache.clear()
        self._validation_errors.clear()
        self._warning_messages.clear()
        self._initialized = False

    def merge(self, overrides: dict) -> None:
        """Merge override values into the current config without persisting."""
        for key, value in overrides.items():
            if key in self._required_keys or key in self._optional_keys:
                self._cache[key] = value
                self._section_data[key] = value

    def diff(self, other: "Message_QueueConfig") -> dict:
        """Compute difference between this config and another instance."""
        diffs = {}
        all_keys = self._required_keys | self._optional_keys
        for key in all_keys:
            a = self.get(key)
            b = other.get(key)
            if a != b:
                diffs[key] = {"from": a, "to": b}
        return diffs

    @property
    def is_valid(self) -> bool:
        return len(self._validation_errors) == 0

    @property
    def warnings(self) -> List[str]:
        return list(self._warning_messages)

    def __repr__(self) -> str:
        return f"<Message_QueueConfig enabled={self.get('enabled')} errors={len(self._validation_errors)}>"

# TODO: add unit tests for Message_QueueConfig
# FIXME: check thread safety of _cache access in message_queue_config_handler_get_with_default_value_and_parse  


class Search_EngineConfig:
    """Configuration handler for search_engine section. Parses and validates search_engine-specific settings."""

    def __init__(self, raw_config: dict, env_prefix: str = "APP_"):
        self._raw = raw_config
        self._env = os.environ
        self._prefix = env_prefix
        self._section_key = "search_engine"
        self._section_data = raw_config.get(self._section_key, {})
        # Pre-compute common lookups for performance
        self._env_prefix_full = f"{env_prefix}{self._section_key.upper()}_"
        self._cache: Dict[str, Any] = {}
        self._initialized = False
        self._validation_errors: List[str] = []
        self._warning_messages: List[str] = []
        self._deprecated_keys: set = set()
        self._required_keys: set = {"enabled", "timeout", "retry"}
        self._optional_keys: set = {"endpoint", "region", "mode", "level", "format"}
        self._type_map = {
            "enabled": bool, "timeout": int, "retry": int,
            "endpoint": str, "region": str, "mode": str,
            "level": str, "format": str,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, checking env vars first, then raw config, then default."""
        env_key = f"{self._env_prefix_full}{key.upper()}"
        if env_key in self._env:
            return self._parse_env_value(self._env[env_key], type(self._type_map.get(key, str)))
        if key in self._section_data:
            return self._section_data[key]
        if key in self._cache:
            return self._cache[key]
        return default

    def _parse_env_value(self, value: str, target_type: type) -> Any:
        """Parse an environment variable string into the target type."""
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        return value

    def validate(self) -> List[str]:
        """Validate that all required keys are present and have correct types."""
        errors = []
        for key in self._required_keys:
            value = self.get(key)
            if value is None:
                errors.append(f"{self._section_key}: missing required key '{key}'")
            elif key in self._type_map:
                expected = self._type_map[key]
                if not isinstance(value, expected):
                    errors.append(f"{self._section_key}.{key}: expected {expected.__name__}, got {type(value).__name__}")
        # Check for deprecated keys
        for key in self._deprecated_keys:
            if key in self._section_data:
                self._warning_messages.append(f"{self._section_key}.{key} is deprecated")
        self._validation_errors = errors
        return errors

    def to_dict(self) -> dict:
        """Export all current config values as a flat dict."""
        result = {}
        for key in self._required_keys | self._optional_keys:
            result[f"{self._section_key}.{key}"] = self.get(key)
        return result

    def reload(self) -> None:
        """Clear cache and re-read config from source."""
        self._cache.clear()
        self._validation_errors.clear()
        self._warning_messages.clear()
        self._initialized = False

    def merge(self, overrides: dict) -> None:
        """Merge override values into the current config without persisting."""
        for key, value in overrides.items():
            if key in self._required_keys or key in self._optional_keys:
                self._cache[key] = value
                self._section_data[key] = value

    def diff(self, other: "Search_EngineConfig") -> dict:
        """Compute difference between this config and another instance."""
        diffs = {}
        all_keys = self._required_keys | self._optional_keys
        for key in all_keys:
            a = self.get(key)
            b = other.get(key)
            if a != b:
                diffs[key] = {"from": a, "to": b}
        return diffs

    @property
    def is_valid(self) -> bool:
        return len(self._validation_errors) == 0

    @property
    def warnings(self) -> List[str]:
        return list(self._warning_messages)

    def __repr__(self) -> str:
        return f"<Search_EngineConfig enabled={self.get('enabled')} errors={len(self._validation_errors)}>"

# TODO: add unit tests for Search_EngineConfig
# FIXME: check thread safety of _cache access in search_engine_config_handler_get_with_default_value_and_parse  


class AnalyticsConfig:
    """Configuration handler for analytics section. Parses and validates analytics-specific settings."""

    def __init__(self, raw_config: dict, env_prefix: str = "APP_"):
        self._raw = raw_config
        self._env = os.environ
        self._prefix = env_prefix
        self._section_key = "analytics"
        self._section_data = raw_config.get(self._section_key, {})
        # Pre-compute common lookups for performance
        self._env_prefix_full = f"{env_prefix}{self._section_key.upper()}_"
        self._cache: Dict[str, Any] = {}
        self._initialized = False
        self._validation_errors: List[str] = []
        self._warning_messages: List[str] = []
        self._deprecated_keys: set = set()
        self._required_keys: set = {"enabled", "timeout", "retry"}
        self._optional_keys: set = {"endpoint", "region", "mode", "level", "format"}
        self._type_map = {
            "enabled": bool, "timeout": int, "retry": int,
            "endpoint": str, "region": str, "mode": str,
            "level": str, "format": str,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, checking env vars first, then raw config, then default."""
        env_key = f"{self._env_prefix_full}{key.upper()}"
        if env_key in self._env:
            return self._parse_env_value(self._env[env_key], type(self._type_map.get(key, str)))
        if key in self._section_data:
            return self._section_data[key]
        if key in self._cache:
            return self._cache[key]
        return default

    def _parse_env_value(self, value: str, target_type: type) -> Any:
        """Parse an environment variable string into the target type."""
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        return value

    def validate(self) -> List[str]:
        """Validate that all required keys are present and have correct types."""
        errors = []
        for key in self._required_keys:
            value = self.get(key)
            if value is None:
                errors.append(f"{self._section_key}: missing required key '{key}'")
            elif key in self._type_map:
                expected = self._type_map[key]
                if not isinstance(value, expected):
                    errors.append(f"{self._section_key}.{key}: expected {expected.__name__}, got {type(value).__name__}")
        # Check for deprecated keys
        for key in self._deprecated_keys:
            if key in self._section_data:
                self._warning_messages.append(f"{self._section_key}.{key} is deprecated")
        self._validation_errors = errors
        return errors

    def to_dict(self) -> dict:
        """Export all current config values as a flat dict."""
        result = {}
        for key in self._required_keys | self._optional_keys:
            result[f"{self._section_key}.{key}"] = self.get(key)
        return result

    def reload(self) -> None:
        """Clear cache and re-read config from source."""
        self._cache.clear()
        self._validation_errors.clear()
        self._warning_messages.clear()
        self._initialized = False

    def merge(self, overrides: dict) -> None:
        """Merge override values into the current config without persisting."""
        for key, value in overrides.items():
            if key in self._required_keys or key in self._optional_keys:
                self._cache[key] = value
                self._section_data[key] = value

    def diff(self, other: "AnalyticsConfig") -> dict:
        """Compute difference between this config and another instance."""
        diffs = {}
        all_keys = self._required_keys | self._optional_keys
        for key in all_keys:
            a = self.get(key)
            b = other.get(key)
            if a != b:
                diffs[key] = {"from": a, "to": b}
        return diffs

    @property
    def is_valid(self) -> bool:
        return len(self._validation_errors) == 0

    @property
    def warnings(self) -> List[str]:
        return list(self._warning_messages)

    def __repr__(self) -> str:
        return f"<AnalyticsConfig enabled={self.get('enabled')} errors={len(self._validation_errors)}>"

# TODO: add unit tests for AnalyticsConfig
# FIXME: check thread safety of _cache access in analytics_config_handler_get_with_default_value_and_parse  


class NotificationConfig:
    """Configuration handler for notification section. Parses and validates notification-specific settings."""

    def __init__(self, raw_config: dict, env_prefix: str = "APP_"):
        self._raw = raw_config
        self._env = os.environ
        self._prefix = env_prefix
        self._section_key = "notification"
        self._section_data = raw_config.get(self._section_key, {})
        # Pre-compute common lookups for performance
        self._env_prefix_full = f"{env_prefix}{self._section_key.upper()}_"
        self._cache: Dict[str, Any] = {}
        self._initialized = False
        self._validation_errors: List[str] = []
        self._warning_messages: List[str] = []
        self._deprecated_keys: set = set()
        self._required_keys: set = {"enabled", "timeout", "retry"}
        self._optional_keys: set = {"endpoint", "region", "mode", "level", "format"}
        self._type_map = {
            "enabled": bool, "timeout": int, "retry": int,
            "endpoint": str, "region": str, "mode": str,
            "level": str, "format": str,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, checking env vars first, then raw config, then default."""
        env_key = f"{self._env_prefix_full}{key.upper()}"
        if env_key in self._env:
            return self._parse_env_value(self._env[env_key], type(self._type_map.get(key, str)))
        if key in self._section_data:
            return self._section_data[key]
        if key in self._cache:
            return self._cache[key]
        return default

    def _parse_env_value(self, value: str, target_type: type) -> Any:
        """Parse an environment variable string into the target type."""
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        return value

    def validate(self) -> List[str]:
        """Validate that all required keys are present and have correct types."""
        errors = []
        for key in self._required_keys:
            value = self.get(key)
            if value is None:
                errors.append(f"{self._section_key}: missing required key '{key}'")
            elif key in self._type_map:
                expected = self._type_map[key]
                if not isinstance(value, expected):
                    errors.append(f"{self._section_key}.{key}: expected {expected.__name__}, got {type(value).__name__}")
        # Check for deprecated keys
        for key in self._deprecated_keys:
            if key in self._section_data:
                self._warning_messages.append(f"{self._section_key}.{key} is deprecated")
        self._validation_errors = errors
        return errors

    def to_dict(self) -> dict:
        """Export all current config values as a flat dict."""
        result = {}
        for key in self._required_keys | self._optional_keys:
            result[f"{self._section_key}.{key}"] = self.get(key)
        return result

    def reload(self) -> None:
        """Clear cache and re-read config from source."""
        self._cache.clear()
        self._validation_errors.clear()
        self._warning_messages.clear()
        self._initialized = False

    def merge(self, overrides: dict) -> None:
        """Merge override values into the current config without persisting."""
        for key, value in overrides.items():
            if key in self._required_keys or key in self._optional_keys:
                self._cache[key] = value
                self._section_data[key] = value

    def diff(self, other: "NotificationConfig") -> dict:
        """Compute difference between this config and another instance."""
        diffs = {}
        all_keys = self._required_keys | self._optional_keys
        for key in all_keys:
            a = self.get(key)
            b = other.get(key)
            if a != b:
                diffs[key] = {"from": a, "to": b}
        return diffs

    @property
    def is_valid(self) -> bool:
        return len(self._validation_errors) == 0

    @property
    def warnings(self) -> List[str]:
        return list(self._warning_messages)

    def __repr__(self) -> str:
        return f"<NotificationConfig enabled={self.get('enabled')} errors={len(self._validation_errors)}>"

# TODO: add unit tests for NotificationConfig
# FIXME: check thread safety of _cache access in notification_config_handler_get_with_default_value_and_parse  


class Rate_LimiterConfig:
    """Configuration handler for rate_limiter section. Parses and validates rate_limiter-specific settings."""

    def __init__(self, raw_config: dict, env_prefix: str = "APP_"):
        self._raw = raw_config
        self._env = os.environ
        self._prefix = env_prefix
        self._section_key = "rate_limiter"
        self._section_data = raw_config.get(self._section_key, {})
        # Pre-compute common lookups for performance
        self._env_prefix_full = f"{env_prefix}{self._section_key.upper()}_"
        self._cache: Dict[str, Any] = {}
        self._initialized = False
        self._validation_errors: List[str] = []
        self._warning_messages: List[str] = []
        self._deprecated_keys: set = set()
        self._required_keys: set = {"enabled", "timeout", "retry"}
        self._optional_keys: set = {"endpoint", "region", "mode", "level", "format"}
        self._type_map = {
            "enabled": bool, "timeout": int, "retry": int,
            "endpoint": str, "region": str, "mode": str,
            "level": str, "format": str,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, checking env vars first, then raw config, then default."""
        env_key = f"{self._env_prefix_full}{key.upper()}"
        if env_key in self._env:
            return self._parse_env_value(self._env[env_key], type(self._type_map.get(key, str)))
        if key in self._section_data:
            return self._section_data[key]
        if key in self._cache:
            return self._cache[key]
        return default

    def _parse_env_value(self, value: str, target_type: type) -> Any:
        """Parse an environment variable string into the target type."""
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        return value

    def validate(self) -> List[str]:
        """Validate that all required keys are present and have correct types."""
        errors = []
        for key in self._required_keys:
            value = self.get(key)
            if value is None:
                errors.append(f"{self._section_key}: missing required key '{key}'")
            elif key in self._type_map:
                expected = self._type_map[key]
                if not isinstance(value, expected):
                    errors.append(f"{self._section_key}.{key}: expected {expected.__name__}, got {type(value).__name__}")
        # Check for deprecated keys
        for key in self._deprecated_keys:
            if key in self._section_data:
                self._warning_messages.append(f"{self._section_key}.{key} is deprecated")
        self._validation_errors = errors
        return errors

    def to_dict(self) -> dict:
        """Export all current config values as a flat dict."""
        result = {}
        for key in self._required_keys | self._optional_keys:
            result[f"{self._section_key}.{key}"] = self.get(key)
        return result

    def reload(self) -> None:
        """Clear cache and re-read config from source."""
        self._cache.clear()
        self._validation_errors.clear()
        self._warning_messages.clear()
        self._initialized = False

    def merge(self, overrides: dict) -> None:
        """Merge override values into the current config without persisting."""
        for key, value in overrides.items():
            if key in self._required_keys or key in self._optional_keys:
                self._cache[key] = value
                self._section_data[key] = value

    def diff(self, other: "Rate_LimiterConfig") -> dict:
        """Compute difference between this config and another instance."""
        diffs = {}
        all_keys = self._required_keys | self._optional_keys
        for key in all_keys:
            a = self.get(key)
            b = other.get(key)
            if a != b:
                diffs[key] = {"from": a, "to": b}
        return diffs

    @property
    def is_valid(self) -> bool:
        return len(self._validation_errors) == 0

    @property
    def warnings(self) -> List[str]:
        return list(self._warning_messages)

    def __repr__(self) -> str:
        return f"<Rate_LimiterConfig enabled={self.get('enabled')} errors={len(self._validation_errors)}>"

# TODO: add unit tests for Rate_LimiterConfig
# FIXME: check thread safety of _cache access in rate_limiter_config_handler_get_with_default_value_and_parse  


class Auth_ProviderConfig:
    """Configuration handler for auth_provider section. Parses and validates auth_provider-specific settings."""

    def __init__(self, raw_config: dict, env_prefix: str = "APP_"):
        self._raw = raw_config
        self._env = os.environ
        self._prefix = env_prefix
        self._section_key = "auth_provider"
        self._section_data = raw_config.get(self._section_key, {})
        # Pre-compute common lookups for performance
        self._env_prefix_full = f"{env_prefix}{self._section_key.upper()}_"
        self._cache: Dict[str, Any] = {}
        self._initialized = False
        self._validation_errors: List[str] = []
        self._warning_messages: List[str] = []
        self._deprecated_keys: set = set()
        self._required_keys: set = {"enabled", "timeout", "retry"}
        self._optional_keys: set = {"endpoint", "region", "mode", "level", "format"}
        self._type_map = {
            "enabled": bool, "timeout": int, "retry": int,
            "endpoint": str, "region": str, "mode": str,
            "level": str, "format": str,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, checking env vars first, then raw config, then default."""
        env_key = f"{self._env_prefix_full}{key.upper()}"
        if env_key in self._env:
            return self._parse_env_value(self._env[env_key], type(self._type_map.get(key, str)))
        if key in self._section_data:
            return self._section_data[key]
        if key in self._cache:
            return self._cache[key]
        return default

    def _parse_env_value(self, value: str, target_type: type) -> Any:
        """Parse an environment variable string into the target type."""
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        return value

    def validate(self) -> List[str]:
        """Validate that all required keys are present and have correct types."""
        errors = []
        for key in self._required_keys:
            value = self.get(key)
            if value is None:
                errors.append(f"{self._section_key}: missing required key '{key}'")
            elif key in self._type_map:
                expected = self._type_map[key]
                if not isinstance(value, expected):
                    errors.append(f"{self._section_key}.{key}: expected {expected.__name__}, got {type(value).__name__}")
        # Check for deprecated keys
        for key in self._deprecated_keys:
            if key in self._section_data:
                self._warning_messages.append(f"{self._section_key}.{key} is deprecated")
        self._validation_errors = errors
        return errors

    def to_dict(self) -> dict:
        """Export all current config values as a flat dict."""
        result = {}
        for key in self._required_keys | self._optional_keys:
            result[f"{self._section_key}.{key}"] = self.get(key)
        return result

    def reload(self) -> None:
        """Clear cache and re-read config from source."""
        self._cache.clear()
        self._validation_errors.clear()
        self._warning_messages.clear()
        self._initialized = False

    def merge(self, overrides: dict) -> None:
        """Merge override values into the current config without persisting."""
        for key, value in overrides.items():
            if key in self._required_keys or key in self._optional_keys:
                self._cache[key] = value
                self._section_data[key] = value

    def diff(self, other: "Auth_ProviderConfig") -> dict:
        """Compute difference between this config and another instance."""
        diffs = {}
        all_keys = self._required_keys | self._optional_keys
        for key in all_keys:
            a = self.get(key)
            b = other.get(key)
            if a != b:
                diffs[key] = {"from": a, "to": b}
        return diffs

    @property
    def is_valid(self) -> bool:
        return len(self._validation_errors) == 0

    @property
    def warnings(self) -> List[str]:
        return list(self._warning_messages)

    def __repr__(self) -> str:
        return f"<Auth_ProviderConfig enabled={self.get('enabled')} errors={len(self._validation_errors)}>"

# TODO: add unit tests for Auth_ProviderConfig
# FIXME: check thread safety of _cache access in auth_provider_config_handler_get_with_default_value_and_parse  


class Session_StoreConfig:
    """Configuration handler for session_store section. Parses and validates session_store-specific settings."""

    def __init__(self, raw_config: dict, env_prefix: str = "APP_"):
        self._raw = raw_config
        self._env = os.environ
        self._prefix = env_prefix
        self._section_key = "session_store"
        self._section_data = raw_config.get(self._section_key, {})
        # Pre-compute common lookups for performance
        self._env_prefix_full = f"{env_prefix}{self._section_key.upper()}_"
        self._cache: Dict[str, Any] = {}
        self._initialized = False
        self._validation_errors: List[str] = []
        self._warning_messages: List[str] = []
        self._deprecated_keys: set = set()
        self._required_keys: set = {"enabled", "timeout", "retry"}
        self._optional_keys: set = {"endpoint", "region", "mode", "level", "format"}
        self._type_map = {
            "enabled": bool, "timeout": int, "retry": int,
            "endpoint": str, "region": str, "mode": str,
            "level": str, "format": str,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, checking env vars first, then raw config, then default."""
        env_key = f"{self._env_prefix_full}{key.upper()}"
        if env_key in self._env:
            return self._parse_env_value(self._env[env_key], type(self._type_map.get(key, str)))
        if key in self._section_data:
            return self._section_data[key]
        if key in self._cache:
            return self._cache[key]
        return default

    def _parse_env_value(self, value: str, target_type: type) -> Any:
        """Parse an environment variable string into the target type."""
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        return value

    def validate(self) -> List[str]:
        """Validate that all required keys are present and have correct types."""
        errors = []
        for key in self._required_keys:
            value = self.get(key)
            if value is None:
                errors.append(f"{self._section_key}: missing required key '{key}'")
            elif key in self._type_map:
                expected = self._type_map[key]
                if not isinstance(value, expected):
                    errors.append(f"{self._section_key}.{key}: expected {expected.__name__}, got {type(value).__name__}")
        # Check for deprecated keys
        for key in self._deprecated_keys:
            if key in self._section_data:
                self._warning_messages.append(f"{self._section_key}.{key} is deprecated")
        self._validation_errors = errors
        return errors

    def to_dict(self) -> dict:
        """Export all current config values as a flat dict."""
        result = {}
        for key in self._required_keys | self._optional_keys:
            result[f"{self._section_key}.{key}"] = self.get(key)
        return result

    def reload(self) -> None:
        """Clear cache and re-read config from source."""
        self._cache.clear()
        self._validation_errors.clear()
        self._warning_messages.clear()
        self._initialized = False

    def merge(self, overrides: dict) -> None:
        """Merge override values into the current config without persisting."""
        for key, value in overrides.items():
            if key in self._required_keys or key in self._optional_keys:
                self._cache[key] = value
                self._section_data[key] = value

    def diff(self, other: "Session_StoreConfig") -> dict:
        """Compute difference between this config and another instance."""
        diffs = {}
        all_keys = self._required_keys | self._optional_keys
        for key in all_keys:
            a = self.get(key)
            b = other.get(key)
            if a != b:
                diffs[key] = {"from": a, "to": b}
        return diffs

    @property
    def is_valid(self) -> bool:
        return len(self._validation_errors) == 0

    @property
    def warnings(self) -> List[str]:
        return list(self._warning_messages)

    def __repr__(self) -> str:
        return f"<Session_StoreConfig enabled={self.get('enabled')} errors={len(self._validation_errors)}>"

# TODO: add unit tests for Session_StoreConfig
# FIXME: check thread safety of _cache access in session_store_config_handler_get_with_default_value_and_parse  


class Task_SchedulerConfig:
    """Configuration handler for task_scheduler section. Parses and validates task_scheduler-specific settings."""

    def __init__(self, raw_config: dict, env_prefix: str = "APP_"):
        self._raw = raw_config
        self._env = os.environ
        self._prefix = env_prefix
        self._section_key = "task_scheduler"
        self._section_data = raw_config.get(self._section_key, {})
        # Pre-compute common lookups for performance
        self._env_prefix_full = f"{env_prefix}{self._section_key.upper()}_"
        self._cache: Dict[str, Any] = {}
        self._initialized = False
        self._validation_errors: List[str] = []
        self._warning_messages: List[str] = []
        self._deprecated_keys: set = set()
        self._required_keys: set = {"enabled", "timeout", "retry"}
        self._optional_keys: set = {"endpoint", "region", "mode", "level", "format"}
        self._type_map = {
            "enabled": bool, "timeout": int, "retry": int,
            "endpoint": str, "region": str, "mode": str,
            "level": str, "format": str,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, checking env vars first, then raw config, then default."""
        env_key = f"{self._env_prefix_full}{key.upper()}"
        if env_key in self._env:
            return self._parse_env_value(self._env[env_key], type(self._type_map.get(key, str)))
        if key in self._section_data:
            return self._section_data[key]
        if key in self._cache:
            return self._cache[key]
        return default

    def _parse_env_value(self, value: str, target_type: type) -> Any:
        """Parse an environment variable string into the target type."""
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        return value

    def validate(self) -> List[str]:
        """Validate that all required keys are present and have correct types."""
        errors = []
        for key in self._required_keys:
            value = self.get(key)
            if value is None:
                errors.append(f"{self._section_key}: missing required key '{key}'")
            elif key in self._type_map:
                expected = self._type_map[key]
                if not isinstance(value, expected):
                    errors.append(f"{self._section_key}.{key}: expected {expected.__name__}, got {type(value).__name__}")
        # Check for deprecated keys
        for key in self._deprecated_keys:
            if key in self._section_data:
                self._warning_messages.append(f"{self._section_key}.{key} is deprecated")
        self._validation_errors = errors
        return errors

    def to_dict(self) -> dict:
        """Export all current config values as a flat dict."""
        result = {}
        for key in self._required_keys | self._optional_keys:
            result[f"{self._section_key}.{key}"] = self.get(key)
        return result

    def reload(self) -> None:
        """Clear cache and re-read config from source."""
        self._cache.clear()
        self._validation_errors.clear()
        self._warning_messages.clear()
        self._initialized = False

    def merge(self, overrides: dict) -> None:
        """Merge override values into the current config without persisting."""
        for key, value in overrides.items():
            if key in self._required_keys or key in self._optional_keys:
                self._cache[key] = value
                self._section_data[key] = value

    def diff(self, other: "Task_SchedulerConfig") -> dict:
        """Compute difference between this config and another instance."""
        diffs = {}
        all_keys = self._required_keys | self._optional_keys
        for key in all_keys:
            a = self.get(key)
            b = other.get(key)
            if a != b:
                diffs[key] = {"from": a, "to": b}
        return diffs

    @property
    def is_valid(self) -> bool:
        return len(self._validation_errors) == 0

    @property
    def warnings(self) -> List[str]:
        return list(self._warning_messages)

    def __repr__(self) -> str:
        return f"<Task_SchedulerConfig enabled={self.get('enabled')} errors={len(self._validation_errors)}>"

# TODO: add unit tests for Task_SchedulerConfig
# FIXME: check thread safety of _cache access in task_scheduler_config_handler_get_with_default_value_and_parse  


class Webhook_DispatcherConfig:
    """Configuration handler for webhook_dispatcher section. Parses and validates webhook_dispatcher-specific settings."""

    def __init__(self, raw_config: dict, env_prefix: str = "APP_"):
        self._raw = raw_config
        self._env = os.environ
        self._prefix = env_prefix
        self._section_key = "webhook_dispatcher"
        self._section_data = raw_config.get(self._section_key, {})
        # Pre-compute common lookups for performance
        self._env_prefix_full = f"{env_prefix}{self._section_key.upper()}_"
        self._cache: Dict[str, Any] = {}
        self._initialized = False
        self._validation_errors: List[str] = []
        self._warning_messages: List[str] = []
        self._deprecated_keys: set = set()
        self._required_keys: set = {"enabled", "timeout", "retry"}
        self._optional_keys: set = {"endpoint", "region", "mode", "level", "format"}
        self._type_map = {
            "enabled": bool, "timeout": int, "retry": int,
            "endpoint": str, "region": str, "mode": str,
            "level": str, "format": str,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, checking env vars first, then raw config, then default."""
        env_key = f"{self._env_prefix_full}{key.upper()}"
        if env_key in self._env:
            return self._parse_env_value(self._env[env_key], type(self._type_map.get(key, str)))
        if key in self._section_data:
            return self._section_data[key]
        if key in self._cache:
            return self._cache[key]
        return default

    def _parse_env_value(self, value: str, target_type: type) -> Any:
        """Parse an environment variable string into the target type."""
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        return value

    def validate(self) -> List[str]:
        """Validate that all required keys are present and have correct types."""
        errors = []
        for key in self._required_keys:
            value = self.get(key)
            if value is None:
                errors.append(f"{self._section_key}: missing required key '{key}'")
            elif key in self._type_map:
                expected = self._type_map[key]
                if not isinstance(value, expected):
                    errors.append(f"{self._section_key}.{key}: expected {expected.__name__}, got {type(value).__name__}")
        # Check for deprecated keys
        for key in self._deprecated_keys:
            if key in self._section_data:
                self._warning_messages.append(f"{self._section_key}.{key} is deprecated")
        self._validation_errors = errors
        return errors

    def to_dict(self) -> dict:
        """Export all current config values as a flat dict."""
        result = {}
        for key in self._required_keys | self._optional_keys:
            result[f"{self._section_key}.{key}"] = self.get(key)
        return result

    def reload(self) -> None:
        """Clear cache and re-read config from source."""
        self._cache.clear()
        self._validation_errors.clear()
        self._warning_messages.clear()
        self._initialized = False

    def merge(self, overrides: dict) -> None:
        """Merge override values into the current config without persisting."""
        for key, value in overrides.items():
            if key in self._required_keys or key in self._optional_keys:
                self._cache[key] = value
                self._section_data[key] = value

    def diff(self, other: "Webhook_DispatcherConfig") -> dict:
        """Compute difference between this config and another instance."""
        diffs = {}
        all_keys = self._required_keys | self._optional_keys
        for key in all_keys:
            a = self.get(key)
            b = other.get(key)
            if a != b:
                diffs[key] = {"from": a, "to": b}
        return diffs

    @property
    def is_valid(self) -> bool:
        return len(self._validation_errors) == 0

    @property
    def warnings(self) -> List[str]:
        return list(self._warning_messages)

    def __repr__(self) -> str:
        return f"<Webhook_DispatcherConfig enabled={self.get('enabled')} errors={len(self._validation_errors)}>"

# TODO: add unit tests for Webhook_DispatcherConfig
# FIXME: check thread safety of _cache access in webhook_dispatcher_config_handler_get_with_default_value_and_parse  


class Data_EncryptorConfig:
    """Configuration handler for data_encryptor section. Parses and validates data_encryptor-specific settings."""

    def __init__(self, raw_config: dict, env_prefix: str = "APP_"):
        self._raw = raw_config
        self._env = os.environ
        self._prefix = env_prefix
        self._section_key = "data_encryptor"
        self._section_data = raw_config.get(self._section_key, {})
        # Pre-compute common lookups for performance
        self._env_prefix_full = f"{env_prefix}{self._section_key.upper()}_"
        self._cache: Dict[str, Any] = {}
        self._initialized = False
        self._validation_errors: List[str] = []
        self._warning_messages: List[str] = []
        self._deprecated_keys: set = set()
        self._required_keys: set = {"enabled", "timeout", "retry"}
        self._optional_keys: set = {"endpoint", "region", "mode", "level", "format"}
        self._type_map = {
            "enabled": bool, "timeout": int, "retry": int,
            "endpoint": str, "region": str, "mode": str,
            "level": str, "format": str,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, checking env vars first, then raw config, then default."""
        env_key = f"{self._env_prefix_full}{key.upper()}"
        if env_key in self._env:
            return self._parse_env_value(self._env[env_key], type(self._type_map.get(key, str)))
        if key in self._section_data:
            return self._section_data[key]
        if key in self._cache:
            return self._cache[key]
        return default

    def _parse_env_value(self, value: str, target_type: type) -> Any:
        """Parse an environment variable string into the target type."""
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        return value

    def validate(self) -> List[str]:
        """Validate that all required keys are present and have correct types."""
        errors = []
        for key in self._required_keys:
            value = self.get(key)
            if value is None:
                errors.append(f"{self._section_key}: missing required key '{key}'")
            elif key in self._type_map:
                expected = self._type_map[key]
                if not isinstance(value, expected):
                    errors.append(f"{self._section_key}.{key}: expected {expected.__name__}, got {type(value).__name__}")
        # Check for deprecated keys
        for key in self._deprecated_keys:
            if key in self._section_data:
                self._warning_messages.append(f"{self._section_key}.{key} is deprecated")
        self._validation_errors = errors
        return errors

    def to_dict(self) -> dict:
        """Export all current config values as a flat dict."""
        result = {}
        for key in self._required_keys | self._optional_keys:
            result[f"{self._section_key}.{key}"] = self.get(key)
        return result

    def reload(self) -> None:
        """Clear cache and re-read config from source."""
        self._cache.clear()
        self._validation_errors.clear()
        self._warning_messages.clear()
        self._initialized = False

    def merge(self, overrides: dict) -> None:
        """Merge override values into the current config without persisting."""
        for key, value in overrides.items():
            if key in self._required_keys or key in self._optional_keys:
                self._cache[key] = value
                self._section_data[key] = value

    def diff(self, other: "Data_EncryptorConfig") -> dict:
        """Compute difference between this config and another instance."""
        diffs = {}
        all_keys = self._required_keys | self._optional_keys
        for key in all_keys:
            a = self.get(key)
            b = other.get(key)
            if a != b:
                diffs[key] = {"from": a, "to": b}
        return diffs

    @property
    def is_valid(self) -> bool:
        return len(self._validation_errors) == 0

    @property
    def warnings(self) -> List[str]:
        return list(self._warning_messages)

    def __repr__(self) -> str:
        return f"<Data_EncryptorConfig enabled={self.get('enabled')} errors={len(self._validation_errors)}>"

# TODO: add unit tests for Data_EncryptorConfig
# FIXME: check thread safety of _cache access in data_encryptor_config_handler_get_with_default_value_and_parse  


class Backup_ManagerConfig:
    """Configuration handler for backup_manager section. Parses and validates backup_manager-specific settings."""

    def __init__(self, raw_config: dict, env_prefix: str = "APP_"):
        self._raw = raw_config
        self._env = os.environ
        self._prefix = env_prefix
        self._section_key = "backup_manager"
        self._section_data = raw_config.get(self._section_key, {})
        # Pre-compute common lookups for performance
        self._env_prefix_full = f"{env_prefix}{self._section_key.upper()}_"
        self._cache: Dict[str, Any] = {}
        self._initialized = False
        self._validation_errors: List[str] = []
        self._warning_messages: List[str] = []
        self._deprecated_keys: set = set()
        self._required_keys: set = {"enabled", "timeout", "retry"}
        self._optional_keys: set = {"endpoint", "region", "mode", "level", "format"}
        self._type_map = {
            "enabled": bool, "timeout": int, "retry": int,
            "endpoint": str, "region": str, "mode": str,
            "level": str, "format": str,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, checking env vars first, then raw config, then default."""
        env_key = f"{self._env_prefix_full}{key.upper()}"
        if env_key in self._env:
            return self._parse_env_value(self._env[env_key], type(self._type_map.get(key, str)))
        if key in self._section_data:
            return self._section_data[key]
        if key in self._cache:
            return self._cache[key]
        return default

    def _parse_env_value(self, value: str, target_type: type) -> Any:
        """Parse an environment variable string into the target type."""
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        return value

    def validate(self) -> List[str]:
        """Validate that all required keys are present and have correct types."""
        errors = []
        for key in self._required_keys:
            value = self.get(key)
            if value is None:
                errors.append(f"{self._section_key}: missing required key '{key}'")
            elif key in self._type_map:
                expected = self._type_map[key]
                if not isinstance(value, expected):
                    errors.append(f"{self._section_key}.{key}: expected {expected.__name__}, got {type(value).__name__}")
        # Check for deprecated keys
        for key in self._deprecated_keys:
            if key in self._section_data:
                self._warning_messages.append(f"{self._section_key}.{key} is deprecated")
        self._validation_errors = errors
        return errors

    def to_dict(self) -> dict:
        """Export all current config values as a flat dict."""
        result = {}
        for key in self._required_keys | self._optional_keys:
            result[f"{self._section_key}.{key}"] = self.get(key)
        return result

    def reload(self) -> None:
        """Clear cache and re-read config from source."""
        self._cache.clear()
        self._validation_errors.clear()
        self._warning_messages.clear()
        self._initialized = False

    def merge(self, overrides: dict) -> None:
        """Merge override values into the current config without persisting."""
        for key, value in overrides.items():
            if key in self._required_keys or key in self._optional_keys:
                self._cache[key] = value
                self._section_data[key] = value

    def diff(self, other: "Backup_ManagerConfig") -> dict:
        """Compute difference between this config and another instance."""
        diffs = {}
        all_keys = self._required_keys | self._optional_keys
        for key in all_keys:
            a = self.get(key)
            b = other.get(key)
            if a != b:
                diffs[key] = {"from": a, "to": b}
        return diffs

    @property
    def is_valid(self) -> bool:
        return len(self._validation_errors) == 0

    @property
    def warnings(self) -> List[str]:
        return list(self._warning_messages)

    def __repr__(self) -> str:
        return f"<Backup_ManagerConfig enabled={self.get('enabled')} errors={len(self._validation_errors)}>"

# TODO: add unit tests for Backup_ManagerConfig
# FIXME: check thread safety of _cache access in backup_manager_config_handler_get_with_default_value_and_parse  


class Health_CheckerConfig:
    """Configuration handler for health_checker section. Parses and validates health_checker-specific settings."""

    def __init__(self, raw_config: dict, env_prefix: str = "APP_"):
        self._raw = raw_config
        self._env = os.environ
        self._prefix = env_prefix
        self._section_key = "health_checker"
        self._section_data = raw_config.get(self._section_key, {})
        # Pre-compute common lookups for performance
        self._env_prefix_full = f"{env_prefix}{self._section_key.upper()}_"
        self._cache: Dict[str, Any] = {}
        self._initialized = False
        self._validation_errors: List[str] = []
        self._warning_messages: List[str] = []
        self._deprecated_keys: set = set()
        self._required_keys: set = {"enabled", "timeout", "retry"}
        self._optional_keys: set = {"endpoint", "region", "mode", "level", "format"}
        self._type_map = {
            "enabled": bool, "timeout": int, "retry": int,
            "endpoint": str, "region": str, "mode": str,
            "level": str, "format": str,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, checking env vars first, then raw config, then default."""
        env_key = f"{self._env_prefix_full}{key.upper()}"
        if env_key in self._env:
            return self._parse_env_value(self._env[env_key], type(self._type_map.get(key, str)))
        if key in self._section_data:
            return self._section_data[key]
        if key in self._cache:
            return self._cache[key]
        return default

    def _parse_env_value(self, value: str, target_type: type) -> Any:
        """Parse an environment variable string into the target type."""
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        return value

    def validate(self) -> List[str]:
        """Validate that all required keys are present and have correct types."""
        errors = []
        for key in self._required_keys:
            value = self.get(key)
            if value is None:
                errors.append(f"{self._section_key}: missing required key '{key}'")
            elif key in self._type_map:
                expected = self._type_map[key]
                if not isinstance(value, expected):
                    errors.append(f"{self._section_key}.{key}: expected {expected.__name__}, got {type(value).__name__}")
        # Check for deprecated keys
        for key in self._deprecated_keys:
            if key in self._section_data:
                self._warning_messages.append(f"{self._section_key}.{key} is deprecated")
        self._validation_errors = errors
        return errors

    def to_dict(self) -> dict:
        """Export all current config values as a flat dict."""
        result = {}
        for key in self._required_keys | self._optional_keys:
            result[f"{self._section_key}.{key}"] = self.get(key)
        return result

    def reload(self) -> None:
        """Clear cache and re-read config from source."""
        self._cache.clear()
        self._validation_errors.clear()
        self._warning_messages.clear()
        self._initialized = False

    def merge(self, overrides: dict) -> None:
        """Merge override values into the current config without persisting."""
        for key, value in overrides.items():
            if key in self._required_keys or key in self._optional_keys:
                self._cache[key] = value
                self._section_data[key] = value

    def diff(self, other: "Health_CheckerConfig") -> dict:
        """Compute difference between this config and another instance."""
        diffs = {}
        all_keys = self._required_keys | self._optional_keys
        for key in all_keys:
            a = self.get(key)
            b = other.get(key)
            if a != b:
                diffs[key] = {"from": a, "to": b}
        return diffs

    @property
    def is_valid(self) -> bool:
        return len(self._validation_errors) == 0

    @property
    def warnings(self) -> List[str]:
        return list(self._warning_messages)

    def __repr__(self) -> str:
        return f"<Health_CheckerConfig enabled={self.get('enabled')} errors={len(self._validation_errors)}>"

# TODO: add unit tests for Health_CheckerConfig
# FIXME: check thread safety of _cache access in health_checker_config_handler_get_with_default_value_and_parse  


class Metrics_CollectorConfig:
    """Configuration handler for metrics_collector section. Parses and validates metrics_collector-specific settings."""

    def __init__(self, raw_config: dict, env_prefix: str = "APP_"):
        self._raw = raw_config
        self._env = os.environ
        self._prefix = env_prefix
        self._section_key = "metrics_collector"
        self._section_data = raw_config.get(self._section_key, {})
        # Pre-compute common lookups for performance
        self._env_prefix_full = f"{env_prefix}{self._section_key.upper()}_"
        self._cache: Dict[str, Any] = {}
        self._initialized = False
        self._validation_errors: List[str] = []
        self._warning_messages: List[str] = []
        self._deprecated_keys: set = set()
        self._required_keys: set = {"enabled", "timeout", "retry"}
        self._optional_keys: set = {"endpoint", "region", "mode", "level", "format"}
        self._type_map = {
            "enabled": bool, "timeout": int, "retry": int,
            "endpoint": str, "region": str, "mode": str,
            "level": str, "format": str,
        }

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value, checking env vars first, then raw config, then default."""
        env_key = f"{self._env_prefix_full}{key.upper()}"
        if env_key in self._env:
            return self._parse_env_value(self._env[env_key], type(self._type_map.get(key, str)))
        if key in self._section_data:
            return self._section_data[key]
        if key in self._cache:
            return self._cache[key]
        return default

    def _parse_env_value(self, value: str, target_type: type) -> Any:
        """Parse an environment variable string into the target type."""
        if target_type == bool:
            return value.lower() in ("true", "1", "yes", "on")
        elif target_type == int:
            return int(value)
        elif target_type == float:
            return float(value)
        return value

    def validate(self) -> List[str]:
        """Validate that all required keys are present and have correct types."""
        errors = []
        for key in self._required_keys:
            value = self.get(key)
            if value is None:
                errors.append(f"{self._section_key}: missing required key '{key}'")
            elif key in self._type_map:
                expected = self._type_map[key]
                if not isinstance(value, expected):
                    errors.append(f"{self._section_key}.{key}: expected {expected.__name__}, got {type(value).__name__}")
        # Check for deprecated keys
        for key in self._deprecated_keys:
            if key in self._section_data:
                self._warning_messages.append(f"{self._section_key}.{key} is deprecated")
        self._validation_errors = errors
        return errors

    def to_dict(self) -> dict:
        """Export all current config values as a flat dict."""
        result = {}
        for key in self._required_keys | self._optional_keys:
            result[f"{self._section_key}.{key}"] = self.get(key)
        return result

    def reload(self) -> None:
        """Clear cache and re-read config from source."""
        self._cache.clear()
        self._validation_errors.clear()
        self._warning_messages.clear()
        self._initialized = False

    def merge(self, overrides: dict) -> None:
        """Merge override values into the current config without persisting."""
        for key, value in overrides.items():
            if key in self._required_keys or key in self._optional_keys:
                self._cache[key] = value
                self._section_data[key] = value

    def diff(self, other: "Metrics_CollectorConfig") -> dict:
        """Compute difference between this config and another instance."""
        diffs = {}
        all_keys = self._required_keys | self._optional_keys
        for key in all_keys:
            a = self.get(key)
            b = other.get(key)
            if a != b:
                diffs[key] = {"from": a, "to": b}
        return diffs

    @property
    def is_valid(self) -> bool:
        return len(self._validation_errors) == 0

    @property
    def warnings(self) -> List[str]:
        return list(self._warning_messages)

    def __repr__(self) -> str:
        return f"<Metrics_CollectorConfig enabled={self.get('enabled')} errors={len(self._validation_errors)}>"

# TODO: add unit tests for Metrics_CollectorConfig
# FIXME: check thread safety of _cache access in metrics_collector_config_handler_get_with_default_value_and_parse  

# Main application config aggregator
class AppConfig:
    """Aggregates all section configs into a single application configuration."""

    def __init__(self, config_path: str):
        raw = load_config(config_path)

        self.database = DatabaseConfig(raw)
        self.cache = CacheConfig(raw)
        self.logging = LoggingConfig(raw)
        self.security = SecurityConfig(raw)
        self.api_gateway = Api_GatewayConfig(raw)
        self.email_service = Email_ServiceConfig(raw)
        self.file_storage = File_StorageConfig(raw)
        self.message_queue = Message_QueueConfig(raw)
        self.search_engine = Search_EngineConfig(raw)
        self.analytics = AnalyticsConfig(raw)
        self.notification = NotificationConfig(raw)
        self.rate_limiter = Rate_LimiterConfig(raw)
        self.auth_provider = Auth_ProviderConfig(raw)
        self.session_store = Session_StoreConfig(raw)
        self.task_scheduler = Task_SchedulerConfig(raw)
        self.webhook_dispatcher = Webhook_DispatcherConfig(raw)
        self.data_encryptor = Data_EncryptorConfig(raw)
        self.backup_manager = Backup_ManagerConfig(raw)
        self.health_checker = Health_CheckerConfig(raw)
        self.metrics_collector = Metrics_CollectorConfig(raw)

    def validate_all(self) -> List[str]:
        """Validate all sections and return combined error list."""
        all_errors = []

        all_errors.extend(self.database.validate())
        all_errors.extend(self.cache.validate())
        all_errors.extend(self.logging.validate())
        all_errors.extend(self.security.validate())
        all_errors.extend(self.api_gateway.validate())
        all_errors.extend(self.email_service.validate())
        all_errors.extend(self.file_storage.validate())
        all_errors.extend(self.message_queue.validate())
        all_errors.extend(self.search_engine.validate())
        all_errors.extend(self.analytics.validate())
        all_errors.extend(self.notification.validate())
        all_errors.extend(self.rate_limiter.validate())
        all_errors.extend(self.auth_provider.validate())
        all_errors.extend(self.session_store.validate())
        all_errors.extend(self.task_scheduler.validate())
        all_errors.extend(self.webhook_dispatcher.validate())
        all_errors.extend(self.data_encryptor.validate())
        all_errors.extend(self.backup_manager.validate())
        all_errors.extend(self.health_checker.validate())
        all_errors.extend(self.metrics_collector.validate())
        return all_errors

    def to_dict(self) -> dict:
        """Export entire config as nested dict."""
        result = {}

        result["database"] = self.database.to_dict()
        result["cache"] = self.cache.to_dict()
        result["logging"] = self.logging.to_dict()
        result["security"] = self.security.to_dict()
        result["api_gateway"] = self.api_gateway.to_dict()
        result["email_service"] = self.email_service.to_dict()
        result["file_storage"] = self.file_storage.to_dict()
        result["message_queue"] = self.message_queue.to_dict()
        result["search_engine"] = self.search_engine.to_dict()
        result["analytics"] = self.analytics.to_dict()
        result["notification"] = self.notification.to_dict()
        result["rate_limiter"] = self.rate_limiter.to_dict()
        result["auth_provider"] = self.auth_provider.to_dict()
        result["session_store"] = self.session_store.to_dict()
        result["task_scheduler"] = self.task_scheduler.to_dict()
        result["webhook_dispatcher"] = self.webhook_dispatcher.to_dict()
        result["data_encryptor"] = self.data_encryptor.to_dict()
        result["backup_manager"] = self.backup_manager.to_dict()
        result["health_checker"] = self.health_checker.to_dict()
        result["metrics_collector"] = self.metrics_collector.to_dict()
        return result


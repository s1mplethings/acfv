"""
Configuration module for ACFV
Provides a global config instance that acts like a dictionary
"""

from .config import ConfigManager

# Create a global config instance that behaves like a dict
_config_manager = ConfigManager()

def get(key, default=None):
    """Get configuration value with default fallback"""
    return _config_manager.config.get(key, default)

def update(data):
    """Update configuration data"""
    _config_manager.config.update(data)

def __getitem__(key):
    """Dictionary-style access"""
    return _config_manager.config[key]

def __setitem__(key, value):
    """Dictionary-style assignment"""
    _config_manager.config[key] = value

def __contains__(key):
    """Support 'in' operator"""
    return key in _config_manager.config

# Make this module behave like a dictionary
import sys
current_module = sys.modules[__name__]
current_module.get = get
current_module.update = update
current_module.__getitem__ = __getitem__
current_module.__setitem__ = __setitem__
current_module.__contains__ = __contains__
"""Shared constants for cove CLI modules.

Kept side-effect-free so importing these values never triggers warning
suppression or logging reconfiguration in the importing module.
"""

NGINX_HTTPS_PORT = 443
NGINX_HTTP_PORT = 8080
"""Proxmox VE capability for homelab-harness (docs/spec/capabilities/proxmox.md).

This package imports only ``homelab_harness_sdk``, never the core. So far it
holds the read-only adapter, its typed models, the UPID parser and the
``pveum`` bootstrap renderer; tools, planners and executors come later.
"""

from homelab_harness_proxmox.adapter import ApiToken, Endpoint, ProxmoxClient
from homelab_harness_proxmox.bootstrap import BootstrapRequest, render_bootstrap_script
from homelab_harness_proxmox.errors import TlsVerificationFailed, UnexpectedResponse
from homelab_harness_proxmox.tls import CaBundle, PinnedCertificate, SystemTrust, TlsTrust
from homelab_harness_proxmox.upid import Upid, parse_upid

__all__ = [
    "ApiToken",
    "BootstrapRequest",
    "CaBundle",
    "Endpoint",
    "PinnedCertificate",
    "ProxmoxClient",
    "SystemTrust",
    "TlsTrust",
    "TlsVerificationFailed",
    "UnexpectedResponse",
    "Upid",
    "parse_upid",
    "render_bootstrap_script",
]

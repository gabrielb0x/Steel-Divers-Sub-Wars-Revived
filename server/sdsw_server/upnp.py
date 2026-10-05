"""UPnP IGD client: asks the router of the server's network to forward the server's ports to it.

Most home routers are UPnP "Internet Gateway Devices": a program on the local network can ask them for their
address on the internet (GetExternalIPAddress) and to forward a port to it (AddPortMapping), through the
WANIPConnection or WANPPPConnection service of their WAN connection device.

  1. discovery (SSDP): an M-SEARCH multicast to 239.255.255.250:1900; the router answers with the URL of its
     description (LOCATION header);
  2. the description (XML) lists the router's services and, for each, a control URL;
  3. actions are SOAP requests (HTTP POST) to the control URL of the WAN connection service.

Standard library only; every call blocks (the server runs them in a thread). Only routers on the local
network are used: a description URL must point to the private address that answered the search.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from xml.sax.saxutils import escape

log = logging.getLogger("upnp")

SSDP_ADDRESS = ("239.255.255.250", 1900)
SEARCH_TARGETS = ("urn:schemas-upnp-org:device:InternetGatewayDevice:1",
                  "urn:schemas-upnp-org:device:InternetGatewayDevice:2",
                  "urn:schemas-upnp-org:service:WANIPConnection:1",
                  "urn:schemas-upnp-org:service:WANPPPConnection:1")
SERVICES = ("urn:schemas-upnp-org:service:WANIPConnection:2",
            "urn:schemas-upnp-org:service:WANIPConnection:1",
            "urn:schemas-upnp-org:service:WANPPPConnection:1")
MAX_DOCUMENT = 256 * 1024
HTTP_TIMEOUT = 4.0

# UPnP error codes (UPnP-gw-WANIPConnection), for the log
ERRORS = {
    402: "invalid arguments", 501: "action failed", 606: "action not authorized by the router",
    714: "no such port mapping", 715: "remote host wildcards not supported",
    716: "external port wildcard not permitted", 718: "port already forwarded to another device",
    724: "external and internal ports must be the same", 725: "the router only accepts permanent leases",
    729: "conflict with another mapping",
}


class UPnPError(Exception):
    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class Gateway:
    control_url: str
    service: str
    local_ip: str            # this machine's address on the router's network: where its forwards point
    name: str = ""           # model of the router, from its description

    def __str__(self) -> str:
        return self.name or urllib.parse.urlsplit(self.control_url).netloc


def _private_host(url: str) -> str | None:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "http" or not parts.hostname:
        return None
    try:
        ip = ipaddress.ip_address(parts.hostname)
    except ValueError:
        return None
    return parts.hostname if ip.version == 4 and not ip.is_global and not ip.is_loopback else None


def search(timeout: float = 2.0) -> list[tuple[str, str]]:
    """SSDP M-SEARCH: (description URL, address that answered), routers first answered first."""
    found: list[tuple[str, str]] = []
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP) as s:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        s.bind(("", 0))
        for target in SEARCH_TARGETS:
            request = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\n"
                       f"MX: 2\r\nST: {target}\r\n\r\n").encode()
            try:
                s.sendto(request, SSDP_ADDRESS)
            except OSError as e:                     # no multicast route: no local network
                log.debug("M-SEARCH: %s", e)
                return []
        deadline = time.monotonic() + timeout
        while (left := deadline - time.monotonic()) > 0:
            s.settimeout(left)
            try:
                data, addr = s.recvfrom(4096)
            except (TimeoutError, socket.timeout):
                break
            except OSError:
                break
            location = search_answer(data, addr[0])
            if location and (location, addr[0]) not in found:
                found.append((location, addr[0]))
    return found


def search_answer(data: bytes, sender: str) -> str | None:
    """LOCATION of an answer to M-SEARCH, when it is the description of the device that answered."""
    lines = data.decode("latin-1").split("\r\n")
    if not (lines[0].upper().startswith("HTTP/1.") and lines[0][8:].split()[:1] == ["200"]):
        return None
    for line in lines[1:]:
        key, sep, value = line.partition(":")
        if sep and key.strip().lower() == "location":
            location = value.strip()
            return location if _private_host(location) == sender else None
    return None


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as answer:      # noqa: S310 (http on the LAN)
        return answer.read(MAX_DOCUMENT)


def _local_ip_towards(host: str, port: int) -> str:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect((host, port))                    # no packet sent: only picks the interface
        return s.getsockname()[0]


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _child_text(element: ET.Element, name: str) -> str:
    for child in element:
        if _tag(child) == name:
            return (child.text or "").strip()
    return ""


def parse_description(xml: bytes, location: str) -> tuple[str, str, str] | None:
    """(control URL, service type, router name) of the best WAN connection service of a description."""
    root = ET.fromstring(xml)
    base = location
    for element in root.iter():
        if _tag(element) == "URLBase" and (element.text or "").strip():
            base = element.text.strip()
    name = ""
    for element in root.iter():
        if _tag(element) == "device":
            name = _child_text(element, "modelName") or _child_text(element, "friendlyName")
            break
    services = {}
    for element in root.iter():
        if _tag(element) == "service":
            kind = _child_text(element, "serviceType")
            control = _child_text(element, "controlURL")
            if kind in SERVICES and control:
                services[kind] = urllib.parse.urljoin(base, control)
    for kind in SERVICES:
        if kind in services:
            return services[kind], kind, name
    return None


def discover(timeout: float = 2.0) -> Gateway | None:
    """The router of this network, if it accepts UPnP requests."""
    for location, address in search(timeout):
        try:
            found = parse_description(_fetch(location), location)
        except (OSError, ET.ParseError, ValueError) as e:
            log.debug("%s: %s", location, e)
            continue
        if found is None:
            continue
        control, service, name = found
        if _private_host(control) != address:      # a description pointing elsewhere: ignored
            continue
        parts = urllib.parse.urlsplit(control)
        try:
            local_ip = _local_ip_towards(address, parts.port or 80)
        except OSError:
            continue
        return Gateway(control, service, local_ip, name)
    return None


def _soap(gateway: Gateway, action: str, arguments: dict[str, object]) -> dict[str, str]:
    body = "".join(f"<{k}>{escape(str(v))}</{k}>" for k, v in arguments.items())
    envelope = ('<?xml version="1.0"?>\r\n<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
                f'<u:{action} xmlns:u="{gateway.service}">{body}</u:{action}></s:Body></s:Envelope>\r\n')
    request = urllib.request.Request(gateway.control_url, data=envelope.encode("utf-8"), method="POST", headers={
        "Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": f'"{gateway.service}#{action}"'})
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as answer:   # noqa: S310
            data = answer.read(MAX_DOCUMENT)
    except urllib.error.HTTPError as e:
        data = e.read(MAX_DOCUMENT)
        code, text = 0, f"HTTP {e.code}"
        try:
            root = ET.fromstring(data)
            for element in root.iter():
                if _tag(element) == "errorCode":
                    code = int((element.text or "0").strip())
                elif _tag(element) == "errorDescription":
                    text = (element.text or "").strip() or text
        except (ET.ParseError, ValueError):
            pass
        raise UPnPError(f"{action}: {ERRORS.get(code, text)}" + (f" (error {code})" if code else ""), code) from None
    except OSError as e:
        raise UPnPError(f"{action}: no answer from the router ({e})") from None
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise UPnPError(f"{action}: unreadable answer from the router ({e})") from None
    return {_tag(element): (element.text or "").strip() for element in root.iter() if _tag(element).startswith("New")}


def external_ip(gateway: Gateway) -> str:
    return _soap(gateway, "GetExternalIPAddress", {}).get("NewExternalIPAddress", "")


def add_mapping(gateway: Gateway, protocol: str, external_port: int, internal_port: int, lease: int,
                description: str, internal_client: str | None = None) -> None:
    _soap(gateway, "AddPortMapping", {
        "NewRemoteHost": "", "NewExternalPort": external_port, "NewProtocol": protocol,
        "NewInternalPort": internal_port, "NewInternalClient": internal_client or gateway.local_ip,
        "NewEnabled": 1, "NewPortMappingDescription": description, "NewLeaseDuration": lease})


def delete_mapping(gateway: Gateway, protocol: str, external_port: int) -> None:
    _soap(gateway, "DeletePortMapping", {"NewRemoteHost": "", "NewExternalPort": external_port,
                                         "NewProtocol": protocol})


def get_mapping(gateway: Gateway, protocol: str, external_port: int) -> dict[str, str] | None:
    """The forward of an external port (NewInternalClient, NewInternalPort...), None when there is none."""
    try:
        return _soap(gateway, "GetSpecificPortMappingEntry", {"NewRemoteHost": "", "NewExternalPort": external_port,
                                                              "NewProtocol": protocol})
    except UPnPError as e:
        if e.code == 714:
            return None
        raise

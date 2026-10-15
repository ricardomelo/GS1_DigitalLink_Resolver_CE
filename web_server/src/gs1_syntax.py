"""
The GS1 Barcode Syntax Engine inside the resolver's own process (deliberate change to the official code).

Every resolution checks the syntax of the GS1 Digital Link it was asked for (GS1-Conformant Resolver 1.2.1, section
2.4). The official code starts a Node.js process for each check (web_logic._call_gs1_toolkit), which costs tens of
milliseconds of CPU: on a two-replica staging installation the resolver saturated at about 26 resolutions a second,
its containers at 100 % CPU and everything else idle. This module asks the same engine — its native library and
Python binding, built at the release docker-compose.yml gives every service (ADR 0003) into GS1_SYNTAX_ENGINE_DIR,
as for the portal — in a few microseconds, and keeps the answers of recent checks.

The engine parses a GS1 Digital Link URI exactly as the Node.js binding does (the same C library at the same
release): data_str for a URI, ai_data_str and get_dl_uri() for an element string. check() answers None when the
engine cannot be loaded; the caller then starts Node.js as before, so a missing library slows the resolver down but
never changes its answers.
"""
import ctypes
import functools
import logging
import os
import sys
import threading

logger = logging.getLogger(__name__)

ENGINE_DIR = os.environ.get("GS1_SYNTAX_ENGINE_DIR", "/opt/gs1-syntax-engine")
# Recent answers kept per process: scans repeat the same codes; serial numbers make every code different, and the
# oldest answers then make room. A few megabytes at most (inputs are short and checked by web_logic first).
CACHE_SIZE = 20000

_load_lock = threading.Lock()
_module = None          # the gs1encoders binding once loaded, False when it cannot be
_errors: tuple = ()
_local = threading.local()


def _load():
    """The engine's Python binding, loaded once per process; None when it is not available."""
    global _module, _errors
    if _module is None:
        with _load_lock:
            if _module is None:
                try:
                    library = ctypes.CDLL(os.path.join(ENGINE_DIR, "libgs1encoders.so"))
                    if ENGINE_DIR not in sys.path:
                        sys.path.insert(0, ENGINE_DIR)
                    # The binding loads "libgs1encoders.so" by name when imported, which would need the directory in
                    # LD_LIBRARY_PATH; it is handed the library loaded from this directory instead (as portal/syntax.py).
                    load_library = ctypes.cdll.LoadLibrary
                    ctypes.cdll.LoadLibrary = lambda name: library if name == "libgs1encoders.so" else load_library(name)
                    try:
                        import gs1encoders  # noqa: PLC0415
                    finally:
                        ctypes.cdll.LoadLibrary = load_library
                    probe = gs1encoders.GS1Encoder()
                    release = probe.version
                    probe.free()
                    _errors = (gs1encoders.GS1EncoderParameterException, gs1encoders.GS1EncoderDigitalLinkException,
                               gs1encoders.GS1EncoderGeneralException)
                    _module = gs1encoders
                    logger.info("GS1 Barcode Syntax Engine %s loaded from %s", release, ENGINE_DIR)
                except Exception as exc:  # noqa: BLE001 — any failure only sends the checks back to Node.js
                    _module = False
                    logger.warning("GS1 Barcode Syntax Engine not loaded from %s (%s: %s): each check starts Node.js",
                                   ENGINE_DIR, type(exc).__name__, exc)
    return _module or None


def available() -> bool:
    """Whether checks run in this process."""
    return _load() is not None


def _encoder():
    """The calling thread's encoder: an engine context is not shared between threads."""
    encoder = getattr(_local, "encoder", None)
    if encoder is None:
        encoder = _local.encoder = _module.GS1Encoder()
    return encoder


@functools.lru_cache(maxsize=CACHE_SIZE)
def _verdict(data: str) -> tuple[bool, str]:
    encoder = _encoder()
    try:
        if data.startswith(("https://", "http://")):
            encoder.data_str = data
        else:
            encoder.ai_data_str = data
            encoder.get_dl_uri(None)
    except _errors as exc:
        return False, str(exc)
    return True, ""


def check(data: str) -> bool | None:
    """Whether a GS1 Digital Link URI (or a bracketed element string) is valid GS1 data; None when the engine is
    not available here."""
    if _load() is None:
        return None
    valid, message = _verdict(data)
    if not valid:
        logger.warning("GS1 Digital Link refused by the GS1 Barcode Syntax Engine: %s: %s", data, message)
    return valid

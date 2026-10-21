"""A small MTP (PTP over USB) client, just enough to sync a Zune HD.

libmtp can't create the Zune's artist objects or set the properties that link
tracks to them, so Clickwheel speaks the protocol itself through pyusb.
"""

from __future__ import annotations

import struct
from collections.abc import Callable, Iterable
from dataclasses import dataclass

import usb.core
import usb.util

# Container types
_COMMAND, _DATA, _RESPONSE = 1, 2, 3

# Response codes
OK = 0x2001
SESSION_ALREADY_OPEN = 0x201E

# Operations
OPEN_SESSION = 0x1002
CLOSE_SESSION = 0x1003
GET_STORAGE_IDS = 0x1004
GET_STORAGE_INFO = 0x1005
GET_OBJECT_HANDLES = 0x1007
DELETE_OBJECT = 0x100B
SEND_OBJECT = 0x100D
GET_DEVICE_PROP_VALUE = 0x1015
SET_DEVICE_PROP_VALUE = 0x1016
GET_OBJECT_REFERENCES = 0x9810
SET_OBJECT_REFERENCES = 0x9811
GET_OBJECT_PROP_VALUE = 0x9803
SET_OBJECT_PROP_VALUE = 0x9804
GET_OBJECT_PROP_LIST = 0x9805
SEND_OBJECT_PROP_LIST = 0x9808

# Data types
INT8, UINT8, INT16, UINT16, INT32, UINT32, INT64, UINT64, INT128, UINT128 = range(1, 11)
AUINT8, AUINT16 = 0x4002, 0x4004
STR = 0xFFFF

_INT_FORMATS = {INT8: "<b", UINT8: "<B", INT16: "<h", UINT16: "<H", INT32: "<i", UINT32: "<I",
                INT64: "<q", UINT64: "<Q"}
_ARRAY_FORMATS = {AUINT8: "B", AUINT16: "H"}

_CHUNK = 512 * 1024
_TIMEOUT_MS = 20000


class MtpError(Exception):
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class DeviceBusy(MtpError):
    """Another program (usually the desktop's MTP handler) has the device open."""


@dataclass(frozen=True)
class Prop:
    """One entry of an object property list."""

    handle: int
    code: int
    type: int
    value: object


def pack_string(text: str) -> bytes:
    if not text:
        return b"\0"
    data = (text + "\0").encode("utf-16-le")
    return struct.pack("<B", len(data) // 2) + data


def unpack_string(data: bytes, offset: int = 0) -> tuple[str, int]:
    count = data[offset]
    end = offset + 1 + 2 * count
    return data[offset + 1:end].decode("utf-16-le").rstrip("\0"), end


def pack_value(type_: int, value) -> bytes:
    if type_ == STR:
        return pack_string(value)
    if type_ in _INT_FORMATS:
        return struct.pack(_INT_FORMATS[type_], value)
    if type_ in (INT128, UINT128):
        return int(value).to_bytes(16, "little", signed=type_ == INT128)
    if type_ in _ARRAY_FORMATS:
        values = list(value)
        return struct.pack(f"<I{len(values)}{_ARRAY_FORMATS[type_]}", len(values), *values)
    raise ValueError(f"unsupported MTP data type {type_:#x}")


def unpack_value(type_: int, data: bytes, offset: int = 0) -> tuple[object, int]:
    if type_ == STR:
        return unpack_string(data, offset)
    if type_ in _INT_FORMATS:
        fmt = _INT_FORMATS[type_]
        return struct.unpack_from(fmt, data, offset)[0], offset + struct.calcsize(fmt)
    if type_ in (INT128, UINT128):
        return int.from_bytes(data[offset:offset + 16], "little", signed=type_ == INT128), offset + 16
    if type_ in _ARRAY_FORMATS:
        (count,) = struct.unpack_from("<I", data, offset)
        fmt = f"<{count}{_ARRAY_FORMATS[type_]}"
        values = struct.unpack_from(fmt, data, offset + 4)
        return (bytes(values) if type_ == AUINT8 else list(values)), offset + 4 + struct.calcsize(fmt)
    raise ValueError(f"unsupported MTP data type {type_:#x}")


def pack_prop_list(props: Iterable[tuple[int, int, object]]) -> bytes:
    """``(code, type, value)`` entries for SendObjectPropList (handle 0 = the new object)."""
    props = list(props)
    out = [struct.pack("<I", len(props))]
    for code, type_, value in props:
        out.append(struct.pack("<IHH", 0, code, type_) + pack_value(type_, value))
    return b"".join(out)


def unpack_prop_list(data: bytes) -> list[Prop]:
    (count,) = struct.unpack_from("<I", data)
    offset, props = 4, []
    for _ in range(count):
        handle, code, type_ = struct.unpack_from("<IHH", data, offset)
        value, offset = unpack_value(type_, data, offset + 8)
        props.append(Prop(handle, code, type_, value))
    return props


def unpack_u32_array(data: bytes) -> list[int]:
    (count,) = struct.unpack_from("<I", data)
    return list(struct.unpack_from(f"<{count}I", data, 4))


def pack_u32_array(values: Iterable[int]) -> bytes:
    values = list(values)
    return struct.pack(f"<I{len(values)}I", len(values), *values)


class MtpDevice:
    """One open MTP session with a USB device."""

    def __init__(self, usb_device):
        self._tid = 0
        self._claimed = False
        self._bind(usb_device)

    def _bind(self, usb_device) -> None:
        self.dev = usb_device
        self.intf = usb_device.get_active_configuration()[(0, 0)]

        def endpoint(direction, kind):
            return usb.util.find_descriptor(
                self.intf, custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == direction
                and usb.util.endpoint_type(e.bmAttributes) == kind)

        self.ep_out = endpoint(usb.util.ENDPOINT_OUT, usb.util.ENDPOINT_TYPE_BULK)
        self.ep_in = endpoint(usb.util.ENDPOINT_IN, usb.util.ENDPOINT_TYPE_BULK)

    @classmethod
    def find(cls, vendor: int, product: int) -> MtpDevice | None:
        dev = usb.core.find(idVendor=vendor, idProduct=product)
        return cls(dev) if dev is not None else None

    # -- session -----------------------------------------------------------

    def open(self) -> None:
        try:
            usb.util.claim_interface(self.dev, self.intf)
        except usb.core.USBError as exc:
            if exc.errno == 16:
                raise DeviceBusy("The device is in use by another program", None) from exc
            raise MtpError(f"Can't open the device: {exc}") from exc
        self._claimed = True
        if self.status() != OK:  # left mid-operation, e.g. by a program that crashed or timed out
            self.reset()
        self._tid = 0  # OpenSession must carry transaction ID 0
        code, _, _ = self._transaction(OPEN_SESSION, (1,))
        if code == SESSION_ALREADY_OPEN:  # left open by an earlier program: start afresh
            self._transaction(CLOSE_SESSION)
            self._tid = 0
            code, _, _ = self._transaction(OPEN_SESSION, (1,))
        if code != OK:
            self.close()
            raise MtpError(f"The device refused to open a session ({code:#06x})", code)

    def close(self) -> None:
        if not self._claimed:
            return
        try:
            self._transaction(CLOSE_SESSION)
        except (usb.core.USBError, MtpError):
            pass
        usb.util.release_interface(self.dev, self.intf)
        usb.util.dispose_resources(self.dev)
        self._claimed = False

    def __enter__(self) -> MtpDevice:
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def status(self) -> int:
        """The device's PTP status code (class request Get Device Status)."""
        try:
            data = bytes(self.dev.ctrl_transfer(0xA1, 0x67, 0, self.intf.bInterfaceNumber, 64, timeout=5000))
            return struct.unpack_from("<H", data, 2)[0]
        except (usb.core.USBError, struct.error):
            return 0

    def reset(self) -> None:
        """Get a device that's stuck mid-operation ready for a new session.

        First the gentle way (Device Reset Request); a Zune still chewing on a
        huge request ignores that, so then a USB port reset, which is what
        unplugging it would do.
        """
        import time

        try:
            self.dev.ctrl_transfer(0x21, 0x66, 0, self.intf.bInterfaceNumber, None, timeout=5000)
        except usb.core.USBError:
            pass
        for ep in (self.ep_in, self.ep_out):
            try:
                self.dev.clear_halt(ep)
            except usb.core.USBError:
                pass
        deadline = time.monotonic() + 5
        while self.status() != OK and time.monotonic() < deadline:
            time.sleep(0.5)
        if self.status() != OK:
            ids = (self.dev.idVendor, self.dev.idProduct)
            try:
                self.dev.reset()
            except usb.core.USBError:
                pass
            deadline = time.monotonic() + 20
            while True:
                time.sleep(1)
                found = usb.core.find(idVendor=ids[0], idProduct=ids[1])
                if found is not None:
                    self._bind(found)
                    if self.status() == OK:
                        usb.util.claim_interface(self.dev, self.intf)
                        break
                if time.monotonic() > deadline:
                    raise MtpError("The device stopped responding; unplug it and plug it back in")
        # Drop anything a cut-off operation left queued.
        try:
            while self.ep_in.read(_CHUNK, timeout=200):
                pass
        except usb.core.USBError:
            pass

    # -- transport ---------------------------------------------------------

    def _transaction(self, op: int, params: tuple[int, ...] = (), data: bytes | None = None,
                     progress: Callable[[int, int], None] | None = None) -> tuple[int, tuple[int, ...], bytes]:
        tid = self._tid
        self._tid += 1
        self.ep_out.write(struct.pack(f"<IHHI{len(params)}I", 12 + 4 * len(params), _COMMAND, op, tid, *params),
                          timeout=_TIMEOUT_MS)
        if data is not None:
            self._send_data(op, tid, data, progress)
        received = b""
        while True:
            buf = self._read_container()
            length, kind, code, _ = struct.unpack_from("<IHHI", buf)
            if kind == _DATA:
                received = buf[12:length]
            elif kind == _RESPONSE:
                n = (length - 12) // 4
                return code, struct.unpack_from(f"<{n}I", buf, 12), received

    def _send_data(self, op: int, tid: int, data: bytes, progress) -> None:
        total = len(data)
        # The Zune rejects a data phase whose header shares a packet with the
        # payload, so (like libmtp) the header goes on its own.
        self.ep_out.write(struct.pack("<IHHI", min(12 + total, 0xFFFFFFFF), _DATA, op, tid), timeout=_TIMEOUT_MS)
        sent = 0
        while sent < total:
            sent += self.ep_out.write(data[sent:sent + _CHUNK], timeout=_TIMEOUT_MS)
            if progress:
                progress(sent, total)
        if total and total % self.ep_out.wMaxPacketSize == 0:
            self.ep_out.write(b"", timeout=_TIMEOUT_MS)  # a short packet ends the transfer

    def _read_container(self) -> bytes:
        buf = bytes(self.ep_in.read(_CHUNK, timeout=_TIMEOUT_MS))
        (length,) = struct.unpack_from("<I", buf)
        while len(buf) < length:
            buf += bytes(self.ep_in.read(_CHUNK, timeout=_TIMEOUT_MS))
        return buf

    def call(self, op: int, *params: int, data: bytes | None = None,
             progress: Callable[[int, int], None] | None = None) -> tuple[tuple[int, ...], bytes]:
        """Run one operation; raise ``MtpError`` unless the device answers OK."""
        code, out_params, received = self._transaction(op, params, data, progress)
        if code != OK:
            raise MtpError(f"MTP operation {op:#06x} failed ({code:#06x})", code)
        return out_params, received

    # -- operations ----------------------------------------------------------

    def storage_ids(self) -> list[int]:
        return unpack_u32_array(self.call(GET_STORAGE_IDS)[1])

    def storage_space(self, storage: int) -> tuple[int, int]:
        """(free, total) bytes."""
        data = self.call(GET_STORAGE_INFO, storage)[1]
        total, free = struct.unpack_from("<QQ", data, 6)
        return free, total

    def object_handles(self, storage: int = 0xFFFFFFFF, fmt: int = 0, parent: int = 0) -> list[int]:
        return unpack_u32_array(self.call(GET_OBJECT_HANDLES, storage, fmt, parent)[1])

    def prop_list(self, handle: int = 0xFFFFFFFF, code: int = 0xFFFFFFFF, fmt: int = 0,
                  depth: int = 0, group: int = 0) -> list[Prop]:
        """Properties of one object, or of every object (handle 0xFFFFFFFF).

        ``code`` 0xFFFFFFFF asks for all properties; ``code`` 0 with a
        ``group`` asks for the device's property group of that number.
        """
        return unpack_prop_list(self.call(GET_OBJECT_PROP_LIST, handle, fmt, code, group, depth)[1])

    def get_prop(self, handle: int, code: int, type_: int):
        return unpack_value(type_, self.call(GET_OBJECT_PROP_VALUE, handle, code)[1])[0]

    def set_prop(self, handle: int, code: int, type_: int, value) -> None:
        self.call(SET_OBJECT_PROP_VALUE, handle, code, data=pack_value(type_, value))

    def get_device_prop(self, code: int, type_: int):
        return unpack_value(type_, self.call(GET_DEVICE_PROP_VALUE, code)[1])[0]

    def set_device_prop(self, code: int, type_: int, value) -> None:
        self.call(SET_DEVICE_PROP_VALUE, code, data=pack_value(type_, value))

    def send_object(self, storage: int, parent: int, fmt: int, props: Iterable[tuple[int, int, object]],
                    data: bytes = b"", progress: Callable[[int, int], None] | None = None,
                    send_data: bool = True) -> int:
        """Create an object from a property list and its contents; returns its handle.

        Abstract objects (albums, artists) still need an empty SendObject to be
        created; folders take none (``send_data=False``), as in libmtp.
        """
        size = len(data)
        out, _ = self.call(SEND_OBJECT_PROP_LIST, storage, parent, fmt, size >> 32, size & 0xFFFFFFFF,
                           data=pack_prop_list(props))
        handle = out[2]
        if send_data:
            self.call(SEND_OBJECT, data=data, progress=progress)
        return handle

    def delete(self, handle: int) -> None:
        self.call(DELETE_OBJECT, handle, 0)

    def references(self, handle: int) -> list[int]:
        return unpack_u32_array(self.call(GET_OBJECT_REFERENCES, handle)[1])

    def set_references(self, handle: int, refs: Iterable[int]) -> None:
        self.call(SET_OBJECT_REFERENCES, handle, data=pack_u32_array(refs))

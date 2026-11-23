"""报警外联动：dryrun（仅日志）/ Snap7（西门子 S7）/ Modbus TCP。

工程细节对齐 HIKONCam 的 PLC 联动设计（仅借鉴思路，不复制代码）：
- 报警 → 置位（DB1.DBX8080.0 口径可配），脉冲 pulse_ms 后自动复位；
- 写失败/断线只记录日志并尝试重连，绝不阻塞检测线程；
- Modbus 侧以线圈（coil）写入等价语义。
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("sv.linkage")


class _DryRunLink:
    def pulse(self) -> bool:
        log.info("联动(dryrun)：已模拟报警置位脉冲")
        return True

    def close(self) -> None:
        pass


class _Snap7Link:
    def __init__(self, cfg: dict) -> None:
        self.host = cfg.get("host", "192.168.2.1")
        self.rack = int(cfg.get("rack", 0))
        self.slot = int(cfg.get("slot", 1))
        self.db = int(cfg.get("db", 1))
        self.byte = int(cfg.get("byte", 8080))
        self.bit = int(cfg.get("bit", 0))
        self.pulse_ms = int(cfg.get("pulse_ms", 500))
        self._cli = None
        self._lock = threading.Lock()

    def _client(self):
        import snap7

        if self._cli is None:
            self._cli = snap7.client.Client()
            self._cli.connect(self.host, self.rack, self.slot)
        elif not self._cli.get_connected():
            self._cli.connect(self.host, self.rack, self.slot)
        return self._cli

    def _write(self, value: bool) -> None:
        cli = self._client()
        data = bytearray(cli.db_read(self.db, self.byte, 1))
        if value:
            data[0] |= 1 << self.bit
        else:
            data[0] &= ~(1 << self.bit)
        cli.db_write(self.db, self.byte, data)

    def pulse(self) -> bool:
        with self._lock:
            self._write(True)
        t = threading.Timer(self.pulse_ms / 1000.0, self._safe_reset)
        t.daemon = True
        t.start()
        return True

    def _safe_reset(self) -> None:
        try:
            with self._lock:
                self._write(False)
        except Exception as exc:
            log.warning("PLC 复位失败（下次调用自动重连）: %s", exc)
            self._cli = None

    def close(self) -> None:
        if self._cli is not None:
            try:
                self._cli.disconnect()
            except Exception:
                pass
            self._cli = None


class _ModbusLink:
    def __init__(self, cfg: dict) -> None:
        self.host = cfg.get("host", "192.168.2.1")
        self.port = int(cfg.get("modbus_port", 502))
        self.coil = int(cfg.get("modbus_coil", 0))
        self.pulse_ms = int(cfg.get("pulse_ms", 500))

    def _write(self, value: bool) -> None:
        from pymodbus.client import ModbusTcpClient

        cli = ModbusTcpClient(self.host, port=self.port, timeout=1.5)
        try:
            if not cli.connect():
                raise ConnectionError(f"Modbus 连接失败 {self.host}:{self.port}")
            cli.write_coil(self.coil, value)
        finally:
            cli.close()

    def pulse(self) -> bool:
        self._write(True)
        t = threading.Timer(self.pulse_ms / 1000.0, self._safe_reset)
        t.daemon = True
        t.start()
        return True

    def _safe_reset(self) -> None:
        try:
            self._write(False)
        except Exception as exc:
            log.warning("Modbus 复位失败: %s", exc)

    def close(self) -> None:
        pass


def _make_driver(cfg: dict):
    driver = (cfg.get("driver") or "dryrun").lower()
    if driver == "snap7":
        return _Snap7Link(cfg)
    if driver == "modbus":
        return _ModbusLink(cfg)
    return _DryRunLink()


class LinkManager:
    """按配置懒加载/重建驱动；线程安全；异常不外抛。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._key = None
        self._driver = None

    def _ensure(self, cfg: dict):
        lc = cfg.get("linkage", {})
        key = (lc.get("driver"), lc.get("host"), lc.get("rack"),
               lc.get("slot"), lc.get("db"), lc.get("byte"), lc.get("bit"),
               lc.get("modbus_port"), lc.get("modbus_coil"),
               lc.get("pulse_ms"))
        with self._lock:
            if key != self._key:
                if self._driver is not None:
                    try:
                        self._driver.close()
                    except Exception:
                        pass
                self._driver = _make_driver(lc)
                self._key = key
            return self._driver

    def notify(self, cfg: dict, alarm: dict) -> bool:
        lc = cfg.get("linkage", {})
        if not lc.get("enabled"):
            return False
        try:
            ok = self._ensure(cfg).pulse()
            log.info("联动置位: [%s] %s", alarm.get("level"), alarm.get("message"))
            return ok
        except Exception as exc:
            log.warning("联动失败（不影响检测）: %s", exc)
            return False

    def test(self, cfg: dict) -> dict:
        lc = cfg.get("linkage", {})
        try:
            self._ensure(cfg).pulse()
            return {"ok": True, "driver": lc.get("driver", "dryrun")}
        except Exception as exc:
            return {"ok": False, "driver": lc.get("driver", "dryrun"),
                    "error": str(exc)}

    def close(self) -> None:
        with self._lock:
            if self._driver is not None:
                try:
                    self._driver.close()
                except Exception:
                    pass
                self._driver = None
                self._key = None


linkage = LinkManager()

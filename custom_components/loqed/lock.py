"""LOQED lock integration for Home Assistant."""
from __future__ import annotations

import asyncio
from datetime import timedelta
import logging
import random
import string

from aiohttp import ClientError
from loqedAPI import loqed
from voluptuous.schema_builder import Undefined

from homeassistant.components import webhook
from homeassistant.components.lock import SUPPORT_OPEN, LockEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_BATTERY_LEVEL,
    STATE_JAMMED,
    STATE_LOCKED,
    STATE_LOCKING,
    STATE_UNLOCKED,
    STATE_UNLOCKING,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, STATE_OPENING, WEBHOOK_PREFIX

LOCK_STATES = {
    "opening": STATE_OPENING,
    "unlocking": STATE_UNLOCKING,
    "locking": STATE_LOCKING,
    "latch": STATE_UNLOCKED,
    "night_lock": STATE_LOCKED,
    "open": STATE_UNLOCKED,
    "day_lock": STATE_UNLOCKED,
}


WEBHOOK_API_ENDPOINT = "/api/loqed/webhook"
SCAN_INTERVAL = timedelta(seconds=300)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
):
    """Set up the Loqed lock platform."""
    data = hass.data[DOMAIN][entry.entry_id]
    _LOGGER.debug("Start setting up the Loqed lock: %s", data["id"])
    websession = async_get_clientsession(hass)
    host = data["host"]
    apiclient = loqed.APIClient(websession, "http://" + host)
    api = loqed.LoqedAPI(apiclient)
    try:
        await api.async_get_lock_details()
    except ClientError:
        host = data["ip"]
        _LOGGER.warning(
            "Unable to use the mdns hostname: %s . Trying with IP-address: %s",
            data["host"],
            data["ip"],
        )
        apiclient = loqed.APIClient(websession, "http://" + host)
        api = loqed.LoqedAPI(apiclient)

    lock = await api.async_get_lock(
        data["api_key"], data["bkey"], data["key_id"], data["name"]
    )
    _LOGGER.debug(
        "Inititated loqed-lock entity with id: %s and host: %s", lock.id, host
    )
    if not lock:
        # No locks found; abort setup routine.
        _LOGGER.info(
            "We cannot connect to the loqed lock, \
                please try to reinstall the integation"
        )
        return
    async_add_entities([LoqedLock(lock, data["internal_url"], "http://" + host)])


def get_random_string(length):
    """Create a rondom ascii string."""
    letters = string.ascii_lowercase
    result_str = "".join(random.choice(letters) for i in range(length))
    return result_str


class LoqedLock(LockEntity):
    """Representation of a loqed lock."""

    def __init__(self, lock: loqed.Lock, internal_url, lock_url) -> None:
        """Initialize the lock."""
        self.lock_url = lock_url
        self._lock = lock
        self._internal_url = internal_url
        self._webhook = ""
        self._attr_unique_id = self._lock.id
        self._attr_name = self._lock.name
        self._attr_supported_features = SUPPORT_OPEN
        # self._attr_supported_features = LockEntityFeature.OPEN
        self.update_task = None

    async def async_added_to_hass(self) -> None:
        """Entity created."""
        await super().async_added_to_hass()
        await self.check_webhook()

    @property
    def changed_by(self):
        """Return true if lock is locking."""
        return "KeyID " + str(self._lock.last_key_id)

    @property
    def bolt_state(self):
        """Return lock bolt state in Loqed format."""
        if self._lock.bolt_state in LOCK_STATES:
            return self._lock.bolt_state
        else:
            return "unknown"

    @property
    def lock_state(self):
        """Return lock bolt state in HASS format."""
        return LOCK_STATES.get(self.bolt_state)

    @property
    def is_locking(self):
        """Return true if lock is locking."""
        return self.lock_state == STATE_LOCKING

    @property
    def is_unlocking(self):
        """Return true if lock is unlocking."""
        return self.lock_state == STATE_UNLOCKING

    @property
    def is_jammed(self):
        """Return true if lock is jammed."""
        return self.lock_state == STATE_JAMMED

    @property
    def is_locked(self):
        """Return true if lock is locked."""
        return self.lock_state== STATE_LOCKED

    @property
    def battery(self):
        """Return true if lock is locked."""
        return self._lock.battery_percentage

    @property
    def extra_state_attributes(self):
        """Extra state attribtues."""
        state_attr = {
            "id": self._lock.id,
            "bolt_state": self.bolt_state,
            "lock_url": self.lock_url,
            "webhook_url": self._webhook,
            ATTR_BATTERY_LEVEL: self._lock.battery_percentage,
            "battery_type": self._lock.battery_type,
            "battery_voltage": self._lock.battery_voltage,
            "wifi_strength": self._lock.wifi_strength,
            "ble_strength": self._lock.ble_strength,
            "last_event": self._lock.last_event,
            # "party_mode": self._lock.party_mode,
            # "guest_access_mode": self._lock.guest_access_mode,
            # "twist_assist": self._lock.twist_assist,
            # "touch_to_connect": self._lock.touch_to_connect,
            # "lock_direction": self._lock.lock_direction,
            # "mortise_lock_type": self._lock.mortise_lock_type,
            "last_changed_key_id": self._lock.last_key_id,
        }
        return state_attr

    async def async_lock(self, **kwargs):
        """To calls the lock method of the loqed lock."""
        _LOGGER.debug("start lock operation")
        await self.async_schedule_update(10)
        await self._lock.lock()

    async def async_unlock(self, **kwargs):
        """To call the unlock method of the loqed lock."""
        _LOGGER.debug("start unlock operation")
        await self.async_schedule_update(10)
        #await self._lock.unlock()

    async def async_open(self, **kwargs):
        """To call the open method of the loqed lock."""
        _LOGGER.debug("start open operation")
        await self.async_schedule_update(10)
        #await self._lock.open()

    async def async_update(self) -> None:
        """To update the internal state of the device."""
        _LOGGER.debug("Start update operation")
        resp = await self._lock.update()
        _LOGGER.debug("Update response: %s", str(resp))
        self._attr_unique_id = self._lock.id
        self._attr_name = self._lock.name
        _LOGGER.debug("BOLT_STATE after update: %s", self.bolt_state)
        self.async_schedule_update_ha_state()

    async def check_webhook(self):
        """Check if webhook is configured on both sides."""
        _LOGGER.debug("Start checking webhooks")
        webhooks = await self._lock.getWebhooks()
        wh_id = Undefined
        # Check if hook already registered @loqed
        for hook in webhooks:
            if hook["url"].startswith(
                self._internal_url + "/api/webhook/" + WEBHOOK_PREFIX
            ):
                url = hook["url"]
                wh_id = WEBHOOK_PREFIX + url[-12:]
                _LOGGER.debug("Found already configured webhook @loqed: %s", url)
                break
        if wh_id == Undefined:
            wh_id = WEBHOOK_PREFIX + get_random_string(12)
            # Registering webhook in Loqed
            url = self._internal_url + "/api/webhook/" + wh_id
            _LOGGER.debug("Registering webhook @loqed: %s", url)
            await self._lock.registerWebhook(url)
        # Registering webhook in HASS, when exists same will be used
        _LOGGER.debug("Registering webhook in HA")
        self._webhook = str(url)
        try:
            webhook.async_register(
                hass=self.hass,
                domain=DOMAIN,
                name="loqed",
                webhook_id=wh_id,
                handler=self.async_handle_webhook,
            )
        except ValueError:  # when already installed
            pass
        return url

    @callback
    async def async_handle_webhook(self, hass, webhook_id, request):
        """Handle webhook callback."""
        _LOGGER.debug("Callback received: %s", str(request.headers))
        received_ts = request.headers["TIMESTAMP"]
        received_hash = request.headers["HASH"]
        body = await request.text()
        _LOGGER.debug("Callback body: %s", body)
        event_data = await self._lock.receiveWebhook(body, received_hash, received_ts)
        if "error" in event_data:
            _LOGGER.warning("Incorrect CALLBACK RECEIVED:: %s", event_data)
            return
        event_type = "LOQED_status_change_to_" + LOCK_STATES[self.bolt_state]
        _LOGGER.debug("Firing event:: %s", event_type)
        hass.bus.fire(event_type, event_data)
        self.async_schedule_update_ha_state(False)
        event = event_data["event_type"].strip().lower()
        if event.split("_")[0] == "state":
            if self.update_task:
                self.update_task.cancel()
        elif "go_to" in event:
            await self.async_schedule_update(12)

    async def async_schedule_update(self, timeout):
        """To cancel outstanding async update task and schedules new one."""
        if self.update_task:
            self.update_task.cancel()
        _LOGGER.debug("PLAN update operation in %s seconds", timeout)
        self.update_task = asyncio.create_task(self.async_delayed_update(timeout))

    async def async_delayed_update(self, timeout):
        """Async update task to handle lock update when nno callback."""
        _LOGGER.debug("Start waiting in delayed_update")
        await asyncio.sleep(timeout)
        await self.async_update()

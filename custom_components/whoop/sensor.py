"""Sensor platform for Whoop integration."""
from datetime import timedelta, datetime
import logging
import json
import requests
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import (
    ATTR_ATTRIBUTION,
    PERCENTAGE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

DOMAIN = "whoop"
SCAN_INTERVAL = timedelta(minutes=5)
ATTRIBUTION = "Data provided by Whoop Integration"

WHOOP_API_URL = None # Will be set during setup
API_TOKEN = None # Will be set during setup

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Whoop sensor."""
    user_id = config_entry.data["user_id"]

    coordinator = WhoopDataUpdateCoordinator(hass, user_id)
    await coordinator.async_config_entry_first_refresh()

    sensors = [
        WhoopRecoverySensor(coordinator),
        WhoopSleepSensor(coordinator),
        WhoopStrainSensor(coordinator),
        WhoopHeartRateSensor(coordinator),
        WhoopWorkoutSensor(coordinator),
    ]

    async_add_entities(sensors, True)

class WhoopDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Whoop data."""

    def __init__(self, hass: HomeAssistant, user_id: str) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.user_id = user_id
        self._last_update = None
        self._session = async_get_clientsession(hass)

    async def _async_update_data(self):
        """Fetch data from Whoop API."""
        try:
            headers = {"X-API-Token": API_TOKEN}
            async with self._session.get(
                f"{WHOOP_API_URL}/data?user_id={self.user_id}",
                headers=headers,
                timeout=10,
            ) as response:
                response.raise_for_status()
                data = await response.json()
                self._last_update = datetime.now()
                return data
        except Exception as err:
            _LOGGER.error("Error fetching Whoop data: %s", err)
            raise

class WhoopSensor(CoordinatorEntity, SensorEntity):
    """Base class for Whoop sensors."""

    def __init__(self, coordinator: WhoopDataUpdateCoordinator) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{self.name}_{coordinator.user_id}"
        self._attr_attribution = ATTRIBUTION

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success

class WhoopRecoverySensor(WhoopSensor):
    """Implementation of a Whoop Recovery sensor."""

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return "Whoop Recovery Score"

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        return PERCENTAGE

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:heart-pulse"

    @property
    def native_value(self) -> float:
        """Return the state of the sensor."""
        try:
            if self.coordinator.data and self.coordinator.data.get("recovery", {}).get("score", {}):
                return self.coordinator.data["recovery"]["score"].get("recovery_score")
        except Exception as err:
            _LOGGER.error("Error getting recovery score: %s", err)
        return None

    @property
    def extra_state_attributes(self) -> dict:
        """Return the state attributes."""
        attrs = {ATTR_ATTRIBUTION: ATTRIBUTION}
        try:
            if self.coordinator.data and self.coordinator.data.get("recovery", {}).get("score", {}):
                score = self.coordinator.data["recovery"]["score"]
                attrs.update({
                    "resting_heart_rate": score.get("resting_heart_rate"),
                    "respiratory_rate": score.get("respiratory_rate"),
                    "spo2_percentage": score.get("spo2_percentage"),
                    "hrv_rmssd": score.get("hrv_rmssd_milli"),
                    "skin_temp_celsius": score.get("skin_temp_celsius"),
                    "user_calibrating": score.get("user_calibrating"),
                    "updated_at": self.coordinator.data["recovery"].get("updated_at"),
                    "created_at": self.coordinator.data["recovery"].get("created_at"),
                    "cycle_id": self.coordinator.data["recovery"].get("cycle_id"),
                    "sleep_id": self.coordinator.data["recovery"].get("sleep_id"),
                })
        except Exception as err:
            _LOGGER.error("Error getting recovery attributes: %s", err)
        return attrs

class WhoopSleepSensor(WhoopSensor):
    """Implementation of a Whoop Sleep sensor."""

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return "Whoop Sleep Score"

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        return PERCENTAGE

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:sleep"

    @property
    def native_value(self) -> float:
        """Return the state of the sensor."""
        try:
            if self.coordinator.data and self.coordinator.data.get("sleep", {}).get("score", {}):
                return self.coordinator.data["sleep"]["score"].get("sleep_performance_percentage")
        except Exception as err:
            _LOGGER.error("Error getting sleep score: %s", err)
        return None

    @property
    def extra_state_attributes(self) -> dict:
        """Return the state attributes."""
        attrs = {ATTR_ATTRIBUTION: ATTRIBUTION}
        try:
            if self.coordinator.data and self.coordinator.data.get("sleep", {}).get("score", {}):
                score = self.coordinator.data["sleep"]["score"]
                stage = score.get("stage_summary", {})
                sleep_needed = score.get("sleep_needed", {})
                attrs.update({
                    "respiratory_rate": score.get("respiratory_rate"),
                    "sleep_consistency": score.get("sleep_consistency_percentage"),
                    "sleep_efficiency": score.get("sleep_efficiency_percentage"),
                    "sleep_cycles": stage.get("sleep_cycle_count"),
                    "disturbances": stage.get("disturbance_count"),
                    "total_sleep_time": stage.get("total_in_bed_time_milli"),
                    "light_sleep_time": stage.get("total_light_sleep_time_milli"),
                    "rem_sleep_time": stage.get("total_rem_sleep_time_milli"),
                    "deep_sleep_time": stage.get("total_slow_wave_sleep_time_milli"),
                    "awake_time": stage.get("total_awake_time_milli"),
                    "start_time": self.coordinator.data["sleep"].get("start"),
                    "end_time": self.coordinator.data["sleep"].get("end"),
                    "baseline_sleep_need": sleep_needed.get("baseline_milli"),
                    "need_from_nap": sleep_needed.get("need_from_recent_nap_milli"),
                    "need_from_strain": sleep_needed.get("need_from_recent_strain_milli"),
                    "need_from_debt": sleep_needed.get("need_from_sleep_debt_milli"),
                })
        except Exception as err:
            _LOGGER.error("Error getting sleep attributes: %s", err)
        return attrs

class WhoopStrainSensor(WhoopSensor):
    """Implementation of a Whoop Strain sensor."""

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return "Whoop Strain Score"

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:lightning-bolt"

    @property
    def native_value(self) -> float:
        """Return the state of the sensor."""
        try:
            if self.coordinator.data and self.coordinator.data.get("cycle", {}).get("score", {}):
                return self.coordinator.data["cycle"]["score"].get("strain")
        except Exception as err:
            _LOGGER.error("Error getting strain score: %s", err)
        return None

    @property
    def extra_state_attributes(self) -> dict:
        """Return the state attributes."""
        attrs = {ATTR_ATTRIBUTION: ATTRIBUTION}
        try:
            if self.coordinator.data and self.coordinator.data.get("cycle", {}).get("score", {}):
                score = self.coordinator.data["cycle"]["score"]
                attrs.update({
                    "kilojoules": score.get("kilojoule"),
                    "average_heart_rate": score.get("average_heart_rate"),
                    "max_heart_rate": score.get("max_heart_rate"),
                    "start_time": self.coordinator.data["cycle"].get("start"),
                    "end_time": self.coordinator.data["cycle"].get("end"),
                    "cycle_id": self.coordinator.data["cycle"].get("id"),
                    "timezone_offset": self.coordinator.data["cycle"].get("timezone_offset"),
                    "score_state": self.coordinator.data["cycle"].get("score_state"),
                })
        except Exception as err:
            _LOGGER.error("Error getting strain attributes: %s", err)
        return attrs

class WhoopHeartRateSensor(WhoopSensor):
    """Implementation of a Whoop Heart Rate sensor."""

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return "Whoop Heart Rate"

    @property
    def native_unit_of_measurement(self) -> str:
        """Return the unit of measurement."""
        return "bpm"

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:heart"

    @property
    def native_value(self) -> int:
        """Return the state of the sensor."""
        try:
            if self.coordinator.data and self.coordinator.data.get("recovery", {}).get("score", {}):
                return self.coordinator.data["recovery"]["score"].get("resting_heart_rate")
        except Exception as err:
            _LOGGER.error("Error getting heart rate: %s", err)
        return None

    @property
    def extra_state_attributes(self) -> dict:
        """Return the state attributes."""
        attrs = {ATTR_ATTRIBUTION: ATTRIBUTION}
        try:
            if self.coordinator.data and self.coordinator.data.get("cycle", {}).get("score", {}):
                cycle_score = self.coordinator.data["cycle"]["score"]
                attrs.update({
                    "max_heart_rate": cycle_score.get("max_heart_rate"),
                    "average_heart_rate": cycle_score.get("average_heart_rate"),
                })
        except Exception as err:
            _LOGGER.error("Error getting heart rate attributes: %s", err)
        return attrs

class WhoopWorkoutSensor(WhoopSensor):
    """Implementation of a Whoop Workout sensor."""

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return "Whoop Workout"

    @property
    def icon(self) -> str:
        """Return the icon."""
        return "mdi:run"

    @property
    def native_value(self) -> float:
        """Return the state of the sensor."""
        try:
            if self.coordinator.data and self.coordinator.data.get("workout", {}).get("score", {}):
                return self.coordinator.data["workout"]["score"].get("strain")
        except Exception as err:
            _LOGGER.error("Error getting workout score: %s", err)
        return None

    @property
    def extra_state_attributes(self) -> dict:
        """Return the state attributes."""
        attrs = {ATTR_ATTRIBUTION: ATTRIBUTION}
        try:
            if self.coordinator.data and self.coordinator.data.get("workout", {}).get("score", {}):
                score = self.coordinator.data["workout"]["score"]
                zone_duration = score.get("zone_duration", {})
                attrs.update({
                    "altitude_change": score.get("altitude_change_meter"),
                    "altitude_gain": score.get("altitude_gain_meter"),
                    "average_heart_rate": score.get("average_heart_rate"),
                    "distance": score.get("distance_meter"),
                    "kilojoules": score.get("kilojoule"),
                    "max_heart_rate": score.get("max_heart_rate"),
                    "percent_recorded": score.get("percent_recorded"),
                    "zone_duration_five": zone_duration.get("zone_five_milli"),
                    "zone_duration_four": zone_duration.get("zone_four_milli"),
                    "zone_duration_three": zone_duration.get("zone_three_milli"),
                    "zone_duration_two": zone_duration.get("zone_two_milli"),
                    "zone_duration_one": zone_duration.get("zone_one_milli"),
                    "zone_duration_zero": zone_duration.get("zone_zero_milli"),
                    "start_time": self.coordinator.data["workout"].get("start"),
                    "end_time": self.coordinator.data["workout"].get("end"),
                    "sport_id": self.coordinator.data["workout"].get("sport_id"),
                    "workout_id": self.coordinator.data["workout"].get("id"),
                })
        except Exception as err:
            _LOGGER.error("Error getting workout attributes: %s", err)
        return attrs
"""Reusable builders for tests.

Thin helpers over ``pykeg.core.defaults`` and the model managers so individual
tests don't repeat the same ``set_defaults`` / ``start_keg`` / temperature-logging
boilerplate. Everything here touches the database, so callers must be inside a
Django test that has DB access (``TestCase`` / ``@pytest.mark.django_db``).
"""

from pykeg.core import defaults, models

DEFAULT_METER = "kegboard.flow0"
SECOND_METER = "kegboard.flow1"


def create_site(set_is_setup=True, create_controller=True):
    """Create the singleton site plus the default taps/controller/meters.

    Returns the ``KegbotSite``. With ``create_controller=True`` you get two taps
    ("Main Tap" / "Second Tap") wired to ``kegboard.flow0`` / ``kegboard.flow1``.
    """
    return defaults.set_defaults(
        set_is_setup=set_is_setup, create_controller=create_controller
    )


def start_keg(
    meter_name=DEFAULT_METER,
    beverage_name="Test Lager",
    producer_name="Test Brewery",
    beverage_type="beer",
    style_name="Lager",
    **kwargs,
):
    """Start a keg on the given meter and return it."""
    return models.Keg.start_keg(
        meter_name,
        beverage_name=beverage_name,
        producer_name=producer_name,
        beverage_type=beverage_type,
        style_name=style_name,
        **kwargs,
    )


def pour(meter_name=DEFAULT_METER, ticks=100, **kwargs):
    """Record a drink on the given meter and return it."""
    return models.Drink.record_drink(meter_name, ticks=ticks, **kwargs)


def attach_temp_sensor(tap, temp_c=4.0, raw_name="thermo0", nice_name="Fridge"):
    """Create a ThermoSensor, bind it to ``tap``, log one reading, and return it.

    ``temp_c`` is in Celsius (the model's native unit).
    """
    sensor = models.ThermoSensor.objects.create(raw_name=raw_name, nice_name=nice_name)
    tap.temperature_sensor = sensor
    tap.save()
    sensor.log_sensor_reading(temp_c)
    return sensor

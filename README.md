# Kegbot Server

This is Kegbot Server, a backend and web interface for monitoring
and managing kegged beverages optimized for running in a Pi.

My repo is forked from the
**Official repository:** https://github.com/Kegbot/kegbot-server/

I have made some changes and improvements to the service which includes:
 * No need for the Android app - enhanced web UI for a real time web UI
 * The deployment expects you to have an Arduino with a Kegboard to hook up the flow and temp sensors, though you may be successful hooking flow sensors directly up to a Pi 
 * Hardware and parts I use:
   * Raspberry Pi 3 B+
   * 7" LCD touch screen with Pi mount to show the web UI in Kiosk mode
   * Arduino Uno with a Kegboard shield, and Kegboard Coaster
   * 2x Swissflow SF-800 flow sensors (I have 2 taps) and 4x John Guest 3/8" Stem OD x 1/4" Hose OD Tube to Hose Stem adapters
   * 1x DS18B20 temperature sensor
   * 3D printed case for the Arduino Uno with Kegboard header




## Quick start

I recommend starting with the Kegberry repo and installing all the services that way: https://github.com/flangelo/kegberry


## Documentation and Help

A lot of this is old, but probably still useful:
* Main project page: https://kegbot.org/
* Docs: https://docs.kegbot.org/
* Discussion forum: https://forum.kegbot.org/
* Discusion Slack group: [Slack link](https://join.slack.com/t/kegbot/shared_invite/zt-3t6rpu9t-AXLNNmL0vPelsbcU6afvjQ)
* [@kegbot](http://twitter.com/kegbot) on Twitter


## Related Projects

* [Kegboard](https://github.com/flangelo/kegboard): Firmware and schematics
  for the Kegbot controller board.
* [Pycore](https://github.com/flangelo/kegbot-pycore): Pycore application.
* [LKegberry](https://github.com/flangelo/kegberry): Main service repo pulling it all together.


## License

All code is offered under the **MIT** license, unless otherwise noted.  Please
see `LICENSE.txt` for the full license.


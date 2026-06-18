#!/bin/bash
# Populate MySQL timezone tables so Django's CONVERT_TZ() works correctly.
mysql_tzinfo_to_sql /usr/share/zoneinfo | mysql -u root mysql

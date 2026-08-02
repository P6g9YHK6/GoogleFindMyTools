#!/bin/sh
set -e

rm -f /tmp/.X99-lock

exec /usr/bin/supervisord -c /etc/supervisor/conf.d/supervisord.conf

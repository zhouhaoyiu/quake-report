#!/bin/sh
set -eu

find /tmp -maxdepth 1 -type d -name 'quake-report-*' -mmin +120 -exec rm -rf {} +

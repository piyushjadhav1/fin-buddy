#!/bin/bash
cd "$(dirname "$0")/finbuddy" || exit 1
python3 server.py

#!/bin/bash

rm -r ./__pycache__
rm -r ./.venv

poetry build

python3 -m venv .venv
source .venv/bin/activate
pip3 install --upgrade pip
pip3 install app-*.whl
gunicorn -c ./gconf.py


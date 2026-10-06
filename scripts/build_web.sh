#!/bin/sh
# Assemble the static site in web/ : the Python package and sample data are
# copied next to the page so the browser worker can fetch them.
set -eu
cd "$(dirname "$0")/.."
rm -rf web/py web/samples
mkdir -p web/py/data_quality web/samples
cp data_quality/*.py web/py/data_quality/
rm -f web/py/data_quality/cli.py web/py/data_quality/__main__.py
cp examples/orders.csv examples/customers.csv examples/orders_rules.json web/samples/
echo "web/ ready"

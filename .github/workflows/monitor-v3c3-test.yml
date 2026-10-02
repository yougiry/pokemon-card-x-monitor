name: Pokemon Card Monitor V3C3 Test

on:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 10

    steps:
      - name: Checkout repository
        uses: actions/checkout@v7

      - name: Set up Python
        uses: actions/setup-python@v6
        with:
          python-version: "3.12"

      - name: Check Python syntax
        run: |
          python -m py_compile monitor_v3c3.py

      - name: Run V3C3 dry test
        env:
          PYTHONUNBUFFERED: "1"
        run: |
          python monitor_v3c3.py

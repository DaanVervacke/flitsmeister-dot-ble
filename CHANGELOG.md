# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
Before 1.0, breaking changes ship as minor bumps.

## [Unreleased]

### Bug Fixes

- Correct the alert cut off byte and documentation drift

### Documentation

- Document the live validation findings and shorten the public docs

### Features

- Add the DOT client with connect, subscribe, reads and state updates
- Validate the protocol against a live DOT capture
- Add animation presets, settings writes and press resolution
- Validate every animation preset against a live DOT
- Read the speech language while connecting and raise DotRejectedError for a refused write
- Recognize a refused read or write reported by an ESPHome Bluetooth proxy
- Connect the scripts through an ESPHome proxy with the habluetooth client wrapper
- Add a live validation script with a file bridge for a driver program

### Maintenance

- Require bleak 3.0.0 or newer



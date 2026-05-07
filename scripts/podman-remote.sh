#!/usr/bin/env bash
# Wrapper used by podman-compose --podman-path so it talks to the host's podman
# socket from inside a Fedora toolbox container.
exec podman --remote "$@"

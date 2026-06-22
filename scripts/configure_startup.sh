#!/usr/bin/env bash
# Runs user-defined startup packages and scripts on every boot.
# Useful for installing tools or running setup that can't be baked into
# the image (HF Space containers are ephemeral, so manual installs are
# lost on restart unless replayed here).
#
# Environment variables:
#   STARTUP_APT_PACKAGES   space-separated apt packages to install
#   STARTUP_PIP_PACKAGES   space-separated pip packages to install
#   STARTUP_NPM_PACKAGES   space-separated npm packages to install
#   STARTUP_RUN            bash commands to execute (multi-line OK)
#   STARTUP_RUN_BASE64     same, but base64-encoded (for complex scripts)
#
# A persistent startup.sh file at data/startup.sh is also run if present.
# Create or edit it from Open Terminal to add commands that run on every
# boot (note: the file itself is ephemeral unless included in backups).
set -uo pipefail

LOG=/home/user/app/data/startup.log
mkdir -p /home/user/app/data
: > "$LOG"

# --- shell-capture wrappers: auto-learn from terminal installs ------------
# Wraps apt/apt-get/pip/pip3/npm/hermes inside the in-browser Terminal so
# that anything you install interactively gets appended to data/startup.sh
# and replayed automatically on the next boot - no need to pre-declare
# packages in STARTUP_*_PACKAGES beforehand. Rewritten (not just appended)
# on every boot so wrapper code changes take effect after an image rebuild
# without leaving stale copies.
BASHRC_FILE="$HOME/.bashrc"
touch "$BASHRC_FILE"
sed -i '/^# >>> hermes shell-capture/,/^# <<< hermes shell-capture/d' "$BASHRC_FILE"
cat >> "$BASHRC_FILE" <<'BASHRC_EOF'
# >>> hermes shell-capture (auto-generated, do not edit) >>>
HERMES_STARTUP_FILE="/home/user/app/data/startup.sh"

_hermes_cap_append() {
    [ "${STARTUP_CAPTURE_DISABLE:-0}" = "1" ] && return 0
    local line="$*"
    mkdir -p "$(dirname "$HERMES_STARTUP_FILE")"
    touch "$HERMES_STARTUP_FILE"
    chmod +x "$HERMES_STARTUP_FILE" 2>/dev/null || true
    grep -qxF "$line" "$HERMES_STARTUP_FILE" 2>/dev/null || echo "$line" >> "$HERMES_STARTUP_FILE"
}
_hermes_cap_quote() {
    local quoted=() arg
    for arg in "$@"; do
        printf -v arg '%q' "$arg"
        quoted+=("$arg")
    done
    printf '%s' "${quoted[*]}"
}
_hermes_cap_append_cmd() {
    local cmd="$1"; shift
    local args
    args=$(_hermes_cap_quote "$@")
    if [ -n "$args" ]; then _hermes_cap_append "$cmd $args"; else _hermes_cap_append "$cmd"; fi
}
_hermes_cap_targets() {
    local arg
    for arg in "$@"; do
        case "$arg" in
            ''|-|--*|-*) ;;
            *) return 0 ;;
        esac
    done
    return 1
}
_hermes_cap_has_arg() {
    local needle="$1"; shift
    local arg
    for arg in "$@"; do [ "$arg" = "$needle" ] && return 0; done
    return 1
}
_hermes_cap_apt_install() {
    if [ "$(id -u)" -eq 0 ]; then command apt-get update && command apt-get install -y "$@"
    elif command -v sudo >/dev/null 2>&1 && sudo -n apt-get --version >/dev/null 2>&1; then
        sudo apt-get update && sudo apt-get install -y "$@"
    else
        echo "Error: apt install needs root." >&2; return 1
    fi
}
apt-get() {
    case "${1:-}" in
        install)
            shift
            _hermes_cap_apt_install "$@"; local rc=$?
            [ $rc -eq 0 ] && _hermes_cap_targets "$@" && _hermes_cap_append_cmd "sudo apt-get update && sudo apt-get install -y" "$@"
            return $rc ;;
        *) command apt-get "$@" ;;
    esac
}
apt() {
    case "${1:-}" in
        install)
            shift
            _hermes_cap_apt_install "$@"; local rc=$?
            [ $rc -eq 0 ] && _hermes_cap_targets "$@" && _hermes_cap_append_cmd "sudo apt-get update && sudo apt-get install -y" "$@"
            return $rc ;;
        *) command apt "$@" ;;
    esac
}
pip() {
    command pip "$@"; local rc=$?
    if [ $rc -eq 0 ] && [ "${1:-}" = "install" ] \
        && ! _hermes_cap_has_arg -r "${@:2}" && ! _hermes_cap_has_arg --requirement "${@:2}" \
        && _hermes_cap_targets "${@:2}"; then
        _hermes_cap_append_cmd "pip install" "${@:2}"
    fi
    return $rc
}
pip3() {
    command pip3 "$@"; local rc=$?
    if [ $rc -eq 0 ] && [ "${1:-}" = "install" ] \
        && ! _hermes_cap_has_arg -r "${@:2}" && ! _hermes_cap_has_arg --requirement "${@:2}" \
        && _hermes_cap_targets "${@:2}"; then
        _hermes_cap_append_cmd "pip install" "${@:2}"
    fi
    return $rc
}
npm() {
    command npm "$@"; local rc=$?
    if [ $rc -eq 0 ] && { [ "${1:-}" = "install" ] || [ "${1:-}" = "i" ]; } \
        && { [ "${2:-}" = "-g" ] || [ "${2:-}" = "--global" ]; } && _hermes_cap_targets "${@:3}"; then
        _hermes_cap_append_cmd "npm install -g" "${@:3}"
    fi
    return $rc
}
hermes() {
    command hermes "$@"; local rc=$?
    if [ $rc -eq 0 ] && [ "${1:-}" = "plugins" ] && [ "${2:-}" = "install" ] && _hermes_cap_targets "${@:3}"; then
        _hermes_cap_append_cmd "hermes plugins install" "${@:3}"
    fi
    return $rc
}
# <<< hermes shell-capture <<<
BASHRC_EOF
echo "[startup] shell-capture wrappers installed in ~/.bashrc" >>"$LOG"

_has_any() {
    [ -n "${1:-}" ]
}

if _has_any "${STARTUP_APT_PACKAGES:-}"; then
    echo "[startup] apt: ${STARTUP_APT_PACKAGES}" >>"$LOG"
    # shellcheck disable=SC2086
    sudo apt-get install -y -qq ${STARTUP_APT_PACKAGES} >>"$LOG" 2>&1 \
        || apt-get install -y -qq ${STARTUP_APT_PACKAGES} >>"$LOG" 2>&1 \
        || echo "[startup] apt install failed (may lack root; install manually)" >>"$LOG"
fi

if _has_any "${STARTUP_PIP_PACKAGES:-}"; then
    echo "[startup] pip: ${STARTUP_PIP_PACKAGES}" >>"$LOG"
    # shellcheck disable=SC2086
    pip install --user -q ${STARTUP_PIP_PACKAGES} >>"$LOG" 2>&1 \
        || echo "[startup] pip install failed" >>"$LOG"
fi

if _has_any "${STARTUP_NPM_PACKAGES:-}"; then
    echo "[startup] npm: ${STARTUP_NPM_PACKAGES}" >>"$LOG"
    # shellcheck disable=SC2086
    npm install -g ${STARTUP_NPM_PACKAGES} >>"$LOG" 2>&1 \
        || echo "[startup] npm install failed" >>"$LOG"
fi

if _has_any "${STARTUP_RUN_BASE64:-}"; then
    echo "[startup] running STARTUP_RUN_BASE64..." >>"$LOG"
    echo "${STARTUP_RUN_BASE64}" | base64 -d | bash >>"$LOG" 2>&1 \
        || echo "[startup] STARTUP_RUN_BASE64 failed" >>"$LOG"
elif _has_any "${STARTUP_RUN:-}"; then
    echo "[startup] running STARTUP_RUN..." >>"$LOG"
    bash -c "${STARTUP_RUN}" >>"$LOG" 2>&1 \
        || echo "[startup] STARTUP_RUN failed" >>"$LOG"
fi

STARTUP_SH="/home/user/app/data/startup.sh"
if [ -f "$STARTUP_SH" ]; then
    echo "[startup] running $STARTUP_SH..." >>"$LOG"
    bash "$STARTUP_SH" >>"$LOG" 2>&1 \
        || echo "[startup] $STARTUP_SH failed" >>"$LOG"
fi

echo "[startup] done." >>"$LOG"

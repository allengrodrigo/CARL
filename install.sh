#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "============================================================"
echo " CARL Installation"
echo "============================================================"
echo

# ---- Find a suitable Python ---------------------------------
# Do not assume that the unversioned `python3` is the best (or even a
# compatible) interpreter.  This is common on macOS, where Apple's Python may
# coexist with a newer python.org, Homebrew, Conda, or pyenv installation.
_python_is_compatible() {
    "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' \
        >/dev/null 2>&1
}

_python_has_tkinter() {
    "$1" -c 'import tkinter' >/dev/null 2>&1
}

_find_python() {
    local candidate resolved fallback=""
    local candidates=()

    # An explicit override wins when it is valid.
    if [ -n "${REQUESTED_PYTHON:-}" ]; then
        candidates+=("$REQUESTED_PYTHON")
    fi

    # First try PATH.  python3 is checked first so an environment selected by
    # pyenv/Conda remains respected; versioned executables provide fallbacks.
    for candidate in python3 python3.11 python3.12 python3.13 python3.10 python3.14 python3.15 python; do
        if resolved="$(command -v "$candidate" 2>/dev/null)"; then
            candidates+=("$resolved")
        fi
    done

    # Then inspect common client-machine locations that may not be on PATH.
    for candidate in \
        /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.10/bin/python3 \
        /Library/Frameworks/Python.framework/Versions/3.14/bin/python3 \
        /opt/homebrew/bin/python3 /usr/local/bin/python3 \
        /opt/homebrew/bin/python3.11 /opt/homebrew/bin/python3.12 \
        /opt/homebrew/bin/python3.13 /opt/homebrew/bin/python3.10 \
        /usr/local/bin/python3.11 /usr/local/bin/python3.12 \
        /usr/local/bin/python3.13 /usr/local/bin/python3.10 \
        "$HOME/miniconda3/bin/python3" "$HOME/anaconda3/bin/python3"; do
        [ -x "$candidate" ] && candidates+=("$candidate")
    done

    for candidate in \
        /Library/Frameworks/Python.framework/Versions/*/bin/python3 \
        /opt/homebrew/bin/python3.* /usr/local/bin/python3.*; do
        [ -x "$candidate" ] && candidates+=("$candidate")
    done

    # pyenv keeps each installed interpreter in its own version directory.
    for candidate in "$HOME"/.pyenv/versions/*/bin/python3; do
        [ -x "$candidate" ] && candidates+=("$candidate")
    done

    # Prefer a compatible interpreter that can actually start this Tk GUI.
    # Keep the first version-compatible interpreter as a diagnostic fallback.
    for candidate in "${candidates[@]}"; do
        [ -x "$candidate" ] || continue
        if _python_is_compatible "$candidate"; then
            [ -n "$fallback" ] || fallback="$candidate"
            if _python_has_tkinter "$candidate"; then
                printf '%s\n' "$candidate"
                return 0
            fi
        fi
    done

    if [ -n "$fallback" ]; then
        printf '%s\n' "$fallback"
        return 0
    fi
    return 1
}

REQUESTED_PYTHON="${CARL_PYTHON:-${PYTHON_BIN:-}}"
if ! PYTHON_BIN="$(_find_python)"; then
    echo "ERROR: No compatible Python installation was found."
    echo "CARL requires Python 3.10 or later (Python 3.11 recommended)."
    echo "Install it from https://www.python.org/downloads/ and run ./install.sh again."
    exit 1
fi

PYTHON_VERSION="$("$PYTHON_BIN" -c 'import platform; print(platform.python_version())')"
echo "Using Python $PYTHON_VERSION: $PYTHON_BIN"

# Lightweight detection mode for support and automated checks.
if [ "${1:-}" = "--detect-python" ]; then
    exit 0
fi

# ---- tkinter check ------------------------------------------
if ! _python_has_tkinter "$PYTHON_BIN"; then
    echo
    echo "WARNING: tkinter is not available in this Python installation."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        echo "On macOS, install Python from https://www.python.org (not Homebrew)"
        echo "or run: brew install python-tk"
    else
        echo "Install the Tk package for this Python (for example, python3-tk on Debian/Ubuntu)."
    fi
    echo
fi

# ---- Create virtual environment -----------------------------
echo
echo "Creating virtual environment..."
if [ -d venv ]; then
    if [ -x venv/bin/python ] && _python_is_compatible venv/bin/python; then
        echo "Compatible virtual environment already exists. Skipping creation."
    else
        BACKUP_DIR="venv.backup.$(date +%Y%m%d-%H%M%S)"
        echo "Existing virtual environment is incompatible; moving it to $BACKUP_DIR"
        mv venv "$BACKUP_DIR"
        "$PYTHON_BIN" -m venv venv
    fi
else
    "$PYTHON_BIN" -m venv venv
fi

# ---- Install requirements -----------------------------------
echo
echo "Installing requirements (this may take several minutes on first run)."
echo "Note: torch is a large download (~200 MB). Please be patient."
echo
venv/bin/python -m pip install --upgrade pip --quiet
venv/bin/python -m pip install -r requirements.txt

# Output Viewer needs both matplotlib's Tk backend and Biopython's tree parser.
# Verify them here so a partial installation fails with a useful message instead
# of waiting until the user opens a tree or image in CARL.
echo
echo "Verifying Output Viewer libraries..."
if ! venv/bin/python -c 'from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg; from Bio import Phylo'; then
    echo "ERROR: Output Viewer libraries could not be imported."
    echo "Please review the installation output above, then run ./install.sh again."
    exit 1
fi
echo "Output Viewer libraries are available."

# ---- Create launcher ----------------------------------------
echo
echo "Creating launcher (run_carl.sh)..."
cat > run_carl.sh << EOF
#!/usr/bin/env bash
exec "${SCRIPT_DIR}/venv/bin/python" "${SCRIPT_DIR}/CARL/run_ui.py" "\$@"
EOF
chmod +x run_carl.sh

echo
echo "============================================================"
echo " Installation complete!"
echo
echo " To start CARL: ./run_carl.sh"
echo "============================================================"
echo
